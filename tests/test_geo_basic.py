from datetime import date

import pandas as pd
import pytest

from app.geo import Station, nearest_station, select_stations


def test_nearest_station_uses_projected_metres():
    stations = [Station("far", 600100, 6200000), Station("near", 600003, 6200004)]
    station, distance = nearest_station(600000, 6200000, stations)
    assert station.station_id == "near"
    assert distance == 5


def test_station_transformation_uses_longitude_then_latitude():
    table = pd.DataFrame([
        {"station_id": "S1", "lon": "9", "lat": "0", "valid_from": "2025-01-01", "valid_to": ""},
    ])
    stations, counts = select_stations(table, date(2025, 1, 1))
    assert stations[0].station_id == "S1"
    assert stations[0].x == pytest.approx(500000, abs=0.001)
    assert stations[0].y == pytest.approx(0, abs=0.001)
    assert counts["station_selected_count"] == 1
