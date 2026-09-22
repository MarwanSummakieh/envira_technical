"""Choose unambiguous station versions and measure distance in EPSG:25832."""
from dataclasses import dataclass
from datetime import date
from math import hypot, isfinite
import re

import pandas as pd
from pyproj import Transformer


@dataclass(frozen=True)
class Station:
    station_id: str
    x: float
    y: float


@dataclass(frozen=True)
class _Version:
    station_id: str
    lon: float
    lat: float
    valid_from: date
    valid_to: date


def _text(value: object) -> str:
    return "" if pd.isna(value) else str(value).strip()


def _date(value: str) -> date:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Station validity dates must be YYYY-MM-DD")
    return date.fromisoformat(value)


def select_stations(
    stations: pd.DataFrame, final_date: date
) -> tuple[list[Station], dict[str, int]]:
    """Select geometry valid on the final date, with inclusive validity bounds.

    Invalid rows are rejected and normalized duplicate versions are collapsed.
    Conflict detection considers only valid rows; a rejected row does not poison
    otherwise valid history for the same ID. Rejection counts must be reviewed.
    An ID with overlapping versions at different coordinates is excluded entirely:
    the source provides no authority with which to resolve the disagreement.
    """
    counts = {
        "station_invalid_rows": 0,
        "station_duplicate_rows": 0,
        "station_conflicting_ids": 0,
        "station_inactive_ids": 0,
        "station_selected_count": 0,
    }
    versions: dict[str, list[_Version]] = {}
    seen: set[_Version] = set()
    for row in stations.itertuples(index=False):
        try:
            station_id = _text(row.station_id)
            lon, lat = float(row.lon), float(row.lat)
            start = _date(_text(row.valid_from))
            end_text = _text(row.valid_to)
            end = _date(end_text) if end_text else date.max
            if (
                not station_id
                or not isfinite(lon)
                or not isfinite(lat)
                or not -180 <= lon <= 180
                or not -90 <= lat <= 90
                or start > end
            ):
                raise ValueError("Invalid station metadata")
        except (ValueError, TypeError):
            counts["station_invalid_rows"] += 1
            continue
        version = _Version(station_id, lon, lat, start, end)
        if version in seen:
            counts["station_duplicate_rows"] += 1
            continue
        seen.add(version)
        versions.setdefault(station_id, []).append(version)

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)
    selected = []
    for station_id, history in sorted(versions.items()):
        conflict = any(
            max(left.valid_from, right.valid_from) <= min(left.valid_to, right.valid_to)
            and (left.lon, left.lat) != (right.lon, right.lat)
            for index, left in enumerate(history)
            for right in history[index + 1 :]
        )
        if conflict:
            counts["station_conflicting_ids"] += 1
            continue
        active = [version for version in history if version.valid_from <= final_date <= version.valid_to]
        if not active:
            counts["station_inactive_ids"] += 1
            continue
        # Every overlapping active version has the same geometry at this point.
        x, y = transformer.transform(active[0].lon, active[0].lat)
        if not isfinite(x) or not isfinite(y):
            counts["station_invalid_rows"] += 1
            continue
        selected.append(Station(station_id, x, y))
    counts["station_selected_count"] = len(selected)
    return selected, counts


def nearest_station(x: float, y: float, stations: list[Station]) -> tuple[Station, float]:
    """Return the nearest station and distance in metres; ties use station ID."""
    if not isfinite(x) or not isfinite(y):
        raise ValueError("Asset coordinates must be finite")
    if not stations:
        raise ValueError("No eligible stations")
    distances = [(station, hypot(station.x - x, station.y - y)) for station in stations]
    if any(not isfinite(distance) for _, distance in distances):
        raise ValueError("Station distances must be finite")
    return min(distances, key=lambda item: (item[1], item[0].station_id))
