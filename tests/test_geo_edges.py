from datetime import date

import pandas as pd
import pytest

from app.geo import Station, nearest_station, select_stations


def version(**overrides):
    row = {
        "station_id": "S1",
        "lon": "9",
        "lat": "56",
        "valid_from": "2025-01-01",
        "valid_to": "",
    }
    return row | overrides


def test_projection_at_utm32_central_meridian():
    stations, _ = select_stations(pd.DataFrame([version()]), date(2025, 1, 1))
    # At longitude 9 degrees, UTM zone 32 has its 500 km false easting.
    # The ellipsoidal meridian arc to latitude 56, scaled by 0.9996,
    # gives approximately 6,206,079.59 m. This does not verify source datum.
    assert stations[0].x == pytest.approx(500000, abs=0.001)
    assert stations[0].y == pytest.approx(6206079.59, abs=0.01)


def test_relocation_selects_versions_at_adjacent_inclusive_boundaries():
    rows = pd.DataFrame([
        version(valid_to="2025-03-15"),
        version(lon="10", valid_from="2025-03-16"),
    ])
    old, old_counts = select_stations(rows, date(2025, 3, 15))
    new, new_counts = select_stations(rows, date(2025, 3, 16))
    assert old[0].station_id == new[0].station_id == "S1"
    assert old[0].x == pytest.approx(500000, abs=0.001)
    assert new[0].x > old[0].x + 60000
    assert old_counts["station_conflicting_ids"] == new_counts["station_conflicting_ids"] == 0


@pytest.mark.parametrize("open_end", ["", "  ", None, float("nan")])
def test_blank_valid_to_is_open_ended(open_end):
    stations, _ = select_stations(pd.DataFrame([version(valid_to=open_end)]), date(2099, 1, 1))
    assert len(stations) == 1


def test_one_shared_boundary_day_with_different_geometry_is_conflict():
    rows = pd.DataFrame([
        version(valid_to="2025-03-15"),
        version(lon="10", valid_from="2025-03-15"),
        version(station_id="S2"),
    ])
    stations, counts = select_stations(rows, date(2025, 3, 16))
    assert [station.station_id for station in stations] == ["S2"]
    assert counts["station_conflicting_ids"] == 1


def test_past_conflict_excludes_entire_id_even_when_final_version_is_unambiguous():
    rows = pd.DataFrame([
        version(valid_to="2025-01-20"),
        version(lon="10", valid_from="2025-01-10", valid_to="2025-01-31"),
        version(lon="11", valid_from="2025-02-01"),
    ])
    stations, counts = select_stations(rows, date(2025, 3, 31))
    assert stations == []
    assert counts["station_conflicting_ids"] == 1


def test_same_location_overlaps_are_usable_and_normalized_duplicates_collapse():
    rows = pd.DataFrame([
        version(station_id=" S1 ", lon="9.0", valid_to="2025-03-15"),
        version(valid_to="2025-03-15"),
        version(valid_from="2025-03-01"),
    ])
    stations, counts = select_stations(rows, date(2025, 3, 15))
    assert [station.station_id for station in stations] == ["S1"]
    assert counts["station_duplicate_rows"] == 1
    assert counts["station_conflicting_ids"] == 0


@pytest.mark.parametrize("invalid", [
    {"station_id": "  "},
    {"station_id": None},
    {"lat": "NaN"},
    {"lat": "91"},
    {"lat": "-91"},
    {"lon": "181"},
    {"lon": "-181"},
    {"lon": "inf"},
    {"lon": "not-a-number"},
    {"lon": None},
    {"valid_from": ""},
    {"valid_from": "20250101"},
    {"valid_from": "2025-1-1"},
    {"valid_from": "2025-02-30"},
    {"valid_to": "2025-02-30"},
    {"valid_from": "2025-03-16", "valid_to": "2025-03-15"},
])
def test_invalid_rows_are_rejected_and_counted(invalid):
    stations, counts = select_stations(pd.DataFrame([version(**invalid)]), date(2025, 3, 31))
    assert stations == []
    assert counts["station_invalid_rows"] == 1


def test_invalid_row_does_not_disqualify_other_valid_history_for_same_id():
    rows = pd.DataFrame([version(), version(lon="181")])
    stations, counts = select_stations(rows, date(2025, 3, 31))
    assert len(stations) == 1
    assert counts["station_invalid_rows"] == 1


def test_no_active_stations_and_no_nearest_station():
    stations, counts = select_stations(
        pd.DataFrame([version(valid_to="2025-03-30")]), date(2025, 3, 31)
    )
    assert stations == []
    assert counts["station_inactive_ids"] == 1
    with pytest.raises(ValueError, match="No eligible stations"):
        nearest_station(500000, 6200000, stations)


def test_equal_distance_ties_are_deterministic_regardless_of_source_order():
    left, right = Station("S2", 499997, 6200004), Station("S1", 500003, 6200004)
    for stations in ([left, right], [right, left]):
        selected, distance = nearest_station(500000, 6200000, stations)
        assert selected.station_id == "S1"
        assert distance == 5


@pytest.mark.parametrize("x,y", [(float("nan"), 0), (0, float("inf"))])
def test_nonfinite_asset_coordinates_are_rejected(x, y):
    with pytest.raises(ValueError, match="Asset coordinates must be finite"):
        nearest_station(x, y, [Station("S1", 500000, 6200000)])


def test_nonfinite_station_distance_is_rejected():
    with pytest.raises(ValueError, match="Station distances must be finite"):
        nearest_station(500000, 6200000, [Station("S1", float("nan"), 6200000)])
