"""Load, validate and prepare static lookups at application startup."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import logging
import math
from pathlib import Path

import pandas as pd
from pyproj import Transformer

from app.exposure import summarize_station
from app.geo import nearest_station, select_stations


logger = logging.getLogger(__name__)


REQUIRED_COLUMNS = {
    "assets": {"asset_id", "address", "x", "y", "asset_type", "insured_value_dkk"},
    "stations": {"station_id", "station_name", "lat", "lon", "valid_from", "valid_to"},
    "observations": {"station_id", "observed_at", "precip_mm", "temp_c"},
}


@dataclass(frozen=True)
class SourceTables:
    assets: pd.DataFrame
    stations: pd.DataFrame
    observations: pd.DataFrame


def load_source_tables(directory: Path) -> SourceTables:
    tables = {}
    for name, required in REQUIRED_COLUMNS.items():
        path = directory / f"{name}.csv"
        try:
            table = pd.read_csv(path, dtype=str, keep_default_na=False)
        except (OSError, ValueError, pd.errors.ParserError) as exc:
            raise ValueError(f"Cannot load required input {path}: {exc}") from exc
        missing = required - set(table.columns)
        if missing:
            raise ValueError(f"{path}: missing required columns: {', '.join(sorted(missing))}")
        if table.empty:
            raise ValueError(f"{path}: no source rows")
        tables[name] = table
    return SourceTables(**tables)


class ConflictingAssetError(ValueError):
    pass


class InvalidAssetError(ValueError):
    pass


class NoEligibleStationError(ValueError):
    pass


@dataclass(frozen=True)
class PreparedData:
    asset_ids: set[str]
    conflicting_assets: set[str]
    invalid_assets: set[str]
    assignments: dict[str, tuple[str, float]]
    summaries: dict[str, dict]
    start: date
    end: date
    quality: dict[str, int]

    def exposure(self, asset_id: str) -> dict:
        if asset_id not in self.asset_ids:
            raise KeyError(asset_id)
        if asset_id in self.conflicting_assets:
            raise ConflictingAssetError(f"Conflicting records for asset {asset_id}")
        if asset_id in self.invalid_assets:
            raise InvalidAssetError(f"Invalid source data for asset {asset_id}")
        if asset_id not in self.assignments:
            raise NoEligibleStationError("No unambiguous station location is valid on the analysis end date")
        station_id, distance = self.assignments[asset_id]
        return {
            "asset_id": asset_id,
            "station_id": station_id,
            "distance_m": round(distance, 2),
            "analysis_period": {"start": self.start, "end": self.end, "timezone": "Europe/Copenhagen"},
            **self.summaries[station_id],
        }


def rainfall(value: str) -> Decimal | None:
    """Preserve decimal thresholds; all negative/sentinel amounts are unknown."""
    try:
        amount = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    return amount if amount.is_finite() and amount >= 0 else None


def prepare_data(source: SourceTables) -> PreparedData:
    quality: dict[str, int] = {}
    assets = source.assets.copy()
    assets["asset_id"] = assets.asset_id.str.strip()
    quality["asset_rows_missing_id"] = int(assets.asset_id.eq("").sum())
    assets = assets.loc[assets.asset_id.ne("")]
    asset_ids = set(assets.asset_id)
    quality["asset_identical_extra_rows"] = int(assets.duplicated().sum())
    assets = assets.drop_duplicates()
    conflicting_assets = set(assets.loc[assets.asset_id.duplicated(False), "asset_id"])
    quality["conflicting_asset_ids"] = len(conflicting_assets)
    coordinates = {}
    invalid_assets = set()
    # The asset source CRS is assumed to equal the chosen metric CRS (identity transform).
    project_assets = Transformer.from_crs(25832, 25832, always_xy=True)
    for row in assets.loc[~assets.asset_id.isin(conflicting_assets)].itertuples(index=False):
        try:
            x, y = project_assets.transform(float(row.x), float(row.y), errcheck=True)
            value = float(row.insured_value_dkk)
            if not all(math.isfinite(v) for v in (x, y, value)) or value < 0:
                raise ValueError("nonfinite or negative value")
            if not str(row.address).strip() or not str(row.asset_type).strip():
                raise ValueError("missing asset metadata")
        except (ValueError, OverflowError):
            invalid_assets.add(row.asset_id)
            continue
        coordinates[row.asset_id] = (x, y)
    quality["invalid_asset_ids"] = len(invalid_assets)

    observations = source.observations.copy()
    quality["observation_identical_extra_rows"] = int(observations.duplicated().sum())
    observations = observations.drop_duplicates()
    observations["station_id"] = observations.station_id.str.strip()
    # Reject naive timestamps instead of silently interpreting them as UTC.
    observations["observed_at"] = observations.observed_at.str.strip()
    aware = observations.observed_at.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$", regex=True)
    timestamps = pd.to_datetime(observations.observed_at.where(aware), utc=True, format="ISO8601", errors="coerce")
    quality["invalid_timestamp_rows"] = int(timestamps.isna().sum())
    if timestamps.notna().sum() == 0:
        raise ValueError("No valid timezone-aware source timestamps")
    local = timestamps.dt.tz_convert("Europe/Copenhagen")
    start, end = local.min().date(), local.max().date()
    observations["observed_at"] = timestamps
    on_schedule = timestamps.dt.hour.isin([23, 5, 11, 17]) & timestamps.dt.minute.eq(0) & timestamps.dt.second.eq(0) & timestamps.dt.microsecond.eq(0) & timestamps.dt.nanosecond.eq(0)
    quality["off_schedule_observation_rows"] = int((timestamps.notna() & ~on_schedule).sum())
    known_stations = set(source.stations.station_id.str.strip()) - {""}
    valid_reference = observations.station_id.isin(known_stations)
    quality["unknown_or_missing_station_rows"] = int((~valid_reference).sum())
    quality["unavailable_rainfall_rows"] = sum(rainfall(value) is None for value in observations.precip_mm)
    usable = observations.loc[timestamps.notna() & on_schedule & valid_reference]
    readings: dict[tuple[str, pd.Timestamp], set[Decimal | None]] = {}
    for row in usable.itertuples(index=False):
        readings.setdefault((row.station_id, row.observed_at), set()).add(rainfall(row.precip_mm))
    quality["conflicting_observation_keys"] = sum(len(values) > 1 for values in readings.values())
    rows = [(sid, timestamp, next(iter(values)) if len(values) == 1 else None)
            for (sid, timestamp), values in readings.items()]
    cleaned = pd.DataFrame(rows, columns=["station_id", "observed_at", "precip_mm"])
    stations, station_quality = select_stations(source.stations, end)
    quality.update(station_quality)
    groups = {sid: group for sid, group in cleaned.groupby("station_id")}
    summaries = {station.station_id: summarize_station(groups.get(station.station_id, cleaned.iloc[:0]), start, end)
                 for station in stations}
    assignments = {}
    if stations:
        for asset_id, (x, y) in coordinates.items():
            station, distance = nearest_station(x, y, stations)
            assignments[asset_id] = (station.station_id, distance)
    # Uvicorn does not configure the root logger at INFO by default. Surface
    # actual quality issues at WARNING so normal launches disclose rejections.
    log = logger.warning if any(value for key, value in quality.items() if key != "station_selected_count") else logger.info
    log("Prepared data quality counts: %s", quality)
    return PreparedData(asset_ids, conflicting_assets, invalid_assets, assignments, summaries, start, end, quality)
