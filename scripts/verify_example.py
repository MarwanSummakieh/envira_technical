"""Independent candidate-data check using csv/datetime/Decimal, then compare HTTP.

This deliberately does not call production cleaning or rainfall functions to
calculate expected results. It is a cross-check for the supplied example asset,
not a second implementation of every input-error policy.
"""
import argparse
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from math import hypot, isclose
from pathlib import Path
from zoneinfo import ZoneInfo

from pyproj import Transformer


def verify(directory: Path) -> dict:
    zone = ZoneInfo("Europe/Copenhagen")
    with (directory / "assets.csv").open(newline="", encoding="utf-8") as file:
        assets = [row for row in csv.DictReader(file) if row["asset_id"] == "A-200975"]
    assert len(assets) == 1, "The example asset must have exactly one source row"
    asset = assets[0]
    with (directory / "observations.csv").open(newline="", encoding="utf-8") as file:
        observations = list(csv.DictReader(file))
    instants = [datetime.fromisoformat(row["observed_at"]) for row in observations]
    first = min(instants).astimezone(zone).date()
    last = max(instants).astimezone(zone).date()
    with (directory / "stations.csv").open(newline="", encoding="utf-8") as file:
        stations = [row for row in csv.DictReader(file)
                    if row["valid_from"] <= last.isoformat()
                    and (not row["valid_to"] or row["valid_to"] >= last.isoformat())]
    transform = Transformer.from_crs(4326, 25832, always_xy=True)
    distances = []
    for station in stations:
        x, y = transform.transform(float(station["lon"]), float(station["lat"]))
        distances.append((hypot(x - float(asset["x"]), y - float(asset["y"])), station["station_id"]))
    distance, station_id = min(distances)
    keyed = {}
    for row, instant in zip(observations, instants):
        if row["station_id"] != station_id:
            continue
        amount = Decimal(row["precip_mm"])
        amount = amount if amount.is_finite() and amount >= 0 else None
        keyed.setdefault(instant, set()).add(amount)

    # Walk the observed fixed UTC clock independently of pandas or app/exposure.py.
    slots = {}
    tick = datetime.combine(first - timedelta(days=1), datetime.min.time(), timezone.utc).replace(hour=23)
    stop = datetime.combine(last + timedelta(days=1), datetime.min.time(), timezone.utc)
    while tick < stop:
        day = tick.astimezone(zone).date()
        if first <= day <= last:
            slots.setdefault(day, []).append(tick)
        tick += timedelta(hours=6)
    totals = {}
    for day, expected in slots.items():
        amounts = [keyed.get(stamp, {None}) for stamp in expected]
        totals[day] = (sum((next(iter(values)) for values in amounts), Decimal(0))
                       if all(len(values) == 1 and None not in values for values in amounts) else None)
    windows = []
    for day in totals:
        dates = [day + timedelta(days=offset) for offset in range(3)]
        values = [totals.get(item) for item in dates]
        if all(value is not None for value in values):
            windows.append((sum(values, Decimal(0)), day))
    worst, window_start = max(windows, key=lambda item: item[0])
    expected = {
        "station_id": station_id, "distance_m": round(distance, 2),
        "wet_day_count": sum(value >= 20 for value in totals.values() if value is not None),
        "worst_three_day_precip_mm": float(worst),
        "coverage": {"complete_days": sum(value is not None for value in totals.values()),
                     "incomplete_days": sum(value is None for value in totals.values()),
                     "eligible_three_day_windows": len(windows)},
    }

    from fastapi.testclient import TestClient
    from app.main import create_app
    with TestClient(create_app(directory)) as client:
        response = client.get("/assets/A-200975/exposure")
    assert response.status_code == 200
    actual = response.json()
    for key, value in expected.items():
        assert actual[key] == value, (key, actual[key], value)
    assert actual["analysis_period"]["start"] == first.isoformat()
    assert actual["analysis_period"]["end"] == last.isoformat()
    # UTM's central meridian has 500 km false easting: independent structural sanity.
    easting, _ = transform.transform(9, 56)
    assert isclose(easting, 500_000, abs_tol=0.001)
    expected["worst_window_daily_mm"] = {
        str(day): str(totals[day])
        for day in (window_start + timedelta(days=offset) for offset in range(3))
    }
    return expected


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, nargs="?", default=Path("data"))
    print(json.dumps(verify(parser.parse_args().directory), indent=2))
