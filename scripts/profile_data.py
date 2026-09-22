"""Read candidate CSVs only; report evidence without cleaning source files."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer


def profile(directory: Path) -> dict:
    frames = {name: pd.read_csv(directory / f"{name}.csv")
              for name in ("assets", "stations", "observations")}
    result = {}
    for name, frame in frames.items():
        keys = {"assets": ["asset_id"], "stations": ["station_id"],
                "observations": ["station_id", "observed_at"]}[name]
        distinct = frame.drop_duplicates()
        result[name] = {
            "rows": len(frame), "unique_keys": len(frame.drop_duplicates(keys)),
            "identical_extra_rows": int(frame.duplicated().sum()),
            "keys_with_different_rows": int((distinct.groupby(keys).size() > 1).sum()),
            "missing_by_column": frame.isna().sum().to_dict(),
        }
    assets, stations, observations = (frames[n] for n in frames)
    for name, columns in (("assets", ["x", "y", "insured_value_dkk"]),
                          ("stations", ["lat", "lon"]),
                          ("observations", ["precip_mm", "temp_c"])):
        for col in columns:
            values = pd.to_numeric(frames[name][col], errors="coerce")
            finite = values[np.isfinite(values)]
            result[name][col] = {"min": float(finite.min()), "max": float(finite.max()),
                                 "nonfinite_or_invalid": int((~np.isfinite(values)).sum()),
                                 "negative": int((values < 0).sum())}
    timestamps = pd.to_datetime(observations.observed_at, utc=True, errors="coerce")
    local = timestamps.dt.tz_convert("Europe/Copenhagen")
    schedule = pd.date_range(timestamps.min(), timestamps.max(), freq="6h")
    result["observations"].update({
        "invalid_timestamps": int(timestamps.isna().sum()),
        "off_schedule_rows": int((~timestamps.isin(schedule)).sum()),
        "expected_slots_per_station": len(schedule),
        "absent_station_timestamp_keys": len(schedule) * stations.station_id.nunique() - len(observations.drop_duplicates(["station_id", "observed_at"])),
        "expected_local_day_slot_counts": schedule.tz_convert("Europe/Copenhagen").normalize().value_counts().value_counts().to_dict(),
        "utc_min": str(timestamps.min()), "utc_max": str(timestamps.max()),
        "local_min": str(local.min()), "local_max": str(local.max()),
        "utc_clock_counts": timestamps.dt.strftime("%H:%M:%S").value_counts().to_dict(),
        "local_clock_counts": local.dt.strftime("%H:%M:%S").value_counts().to_dict(),
        "unknown_station_rows": int((~observations.station_id.isin(stations.station_id)).sum()),
        "precip_conflict_keys": int((observations.groupby(["station_id", "observed_at"])
                                      .precip_mm.nunique(dropna=False) > 1).sum()),
        "negative_precip_values": observations.loc[observations.precip_mm < 0, "precip_mm"].value_counts().to_dict(),
    })
    for date in ("2025-03-30", "2025-10-26", "2026-03-29"):
        subset = observations.loc[local.dt.strftime("%Y-%m-%d") == date]
        result["observations"][date + "_unique_utc_times"] = sorted(subset.observed_at.unique().tolist())
    versions = stations.drop_duplicates()
    begin = pd.to_datetime(versions.valid_from, errors="coerce")
    end = pd.to_datetime(versions.valid_to, errors="coerce")
    result["stations"]["invalid_validity_rows"] = int((begin.isna() | (versions.valid_to.notna() & end.isna()) | (end < begin)).sum())
    result["stations"]["multiple_version_ids"] = versions.loc[versions.station_id.duplicated(False)].astype(object).where(versions.notna(), None).to_dict("records")
    for epsg in (25832, 32632):
        lon, lat = Transformer.from_crs(epsg, 4326, always_xy=True).transform(assets.x, assets.y)
        result["assets"][f"assumed_epsg_{epsg}_geographic_bounds"] = [min(lon), min(lat), max(lon), max(lat)]
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, nargs="?", default=Path("data"))
    print(json.dumps(profile(parser.parse_args().directory), indent=2, default=str))
