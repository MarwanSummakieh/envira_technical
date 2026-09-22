"""Load source tables at startup; cleaning is added in the next stage."""
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


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
            table = pd.read_csv(path, dtype=str)
        except (OSError, ValueError, pd.errors.ParserError) as exc:
            raise ValueError(f"Cannot load required input {path}: {exc}") from exc
        missing = required - set(table.columns)
        if missing:
            raise ValueError(f"{path}: missing required columns: {', '.join(sorted(missing))}")
        if table.empty:
            raise ValueError(f"{path}: no source rows")
        tables[name] = table
    return SourceTables(**tables)
