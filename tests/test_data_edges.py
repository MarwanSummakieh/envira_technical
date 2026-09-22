"""Small, hand-calculated fixtures for source cleaning and HTTP error behavior."""
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient
import pandas as pd
import pytest

from app.data import SourceTables, prepare_data
from app.main import create_app


@pytest.fixture
def source() -> SourceTables:
    # Copenhagen 1 January has four observations totalling exactly 20 mm.
    return SourceTables(
        assets=pd.DataFrame([
            {"asset_id": "A1", "address": "Example", "x": "600000", "y": "6200000",
             "asset_type": "residential", "insured_value_dkk": "1000000"},
        ]),
        stations=pd.DataFrame([
            {"station_id": "S1", "station_name": "Example", "lat": "56", "lon": "10",
             "valid_from": "2025-01-01", "valid_to": ""},
        ]),
        observations=pd.DataFrame([
            {"station_id": "S1", "observed_at": timestamp, "precip_mm": "5", "temp_c": "0"}
            for timestamp in (
                "2024-12-31T23:00:00Z", "2025-01-01T05:00:00Z",
                "2025-01-01T11:00:00Z", "2025-01-01T17:00:00Z",
            )
        ]),
    )


def write_source(source: SourceTables, directory: Path) -> Path:
    for name in ("assets", "stations", "observations"):
        getattr(source, name).to_csv(directory / f"{name}.csv", index=False)
    return directory


@pytest.mark.parametrize("suffix", ["+0000", "+00:00"])
def test_iso_timezone_offsets_with_or_without_colon(source: SourceTables, suffix: str):
    source.observations["observed_at"] = source.observations.observed_at.str.replace("Z", suffix) + " "
    prepared = prepare_data(source)
    assert prepared.quality["invalid_timestamp_rows"] == 0
    assert prepared.start == prepared.end == date(2025, 1, 1)
    assert prepared.exposure("A1")["wet_day_count"] == 1


def test_identical_asset_rows_collapse_without_conflict(source: SourceTables):
    source.assets.loc[1] = source.assets.loc[0]
    prepared = prepare_data(source)
    assert prepared.quality["asset_identical_extra_rows"] == 1
    assert prepared.quality["conflicting_asset_ids"] == 0
    assert prepared.exposure("A1")["wet_day_count"] == 1


def test_conflicting_asset_is_409_but_other_assets_remain_usable(
    source: SourceTables, tmp_path: Path,
):
    source.assets.loc[1] = source.assets.loc[0]
    source.assets.loc[1, "address"] = "Disputed address"
    source.assets.loc[2] = source.assets.loc[0]
    source.assets.loc[2, "asset_id"] = "A2"
    with TestClient(create_app(write_source(source, tmp_path))) as client:
        conflict = client.get("/assets/A1/exposure")
        unaffected = client.get("/assets/A2/exposure")
    assert conflict.status_code == 409
    assert "Conflicting records" in conflict.json()["detail"]
    assert unaffected.status_code == 200
    assert unaffected.json()["wet_day_count"] == 1


@pytest.mark.parametrize("difference", ["identical", "temperature", "numeric_format"])
def test_observation_duplicates_do_not_double_count_rainfall(
    source: SourceTables, difference: str,
):
    source.observations.loc[4] = source.observations.loc[0]
    if difference == "temperature":
        source.observations.loc[4, "temp_c"] = "99"
    elif difference == "numeric_format":
        source.observations.loc[4, "precip_mm"] = "5.00"
    prepared = prepare_data(source)
    result = prepared.exposure("A1")
    assert prepared.quality["observation_identical_extra_rows"] == (1 if difference == "identical" else 0)
    assert prepared.quality["conflicting_observation_keys"] == 0
    assert result["wet_day_count"] == 1  # Four unique readings still total 20 mm.
    assert result["coverage"]["complete_days"] == 1


@pytest.mark.parametrize("conflicting_amount", ["6", "-9999"])
def test_conflicting_rainfall_makes_the_day_unknown(
    source: SourceTables, conflicting_amount: str,
):
    source.observations.loc[4] = source.observations.loc[0]
    source.observations.loc[4, "precip_mm"] = conflicting_amount
    prepared = prepare_data(source)
    result = prepared.exposure("A1")
    assert prepared.quality["conflicting_observation_keys"] == 1
    assert result["wet_day_count"] is None
    assert result["coverage"] == {
        "complete_days": 0, "incomplete_days": 1, "eligible_three_day_windows": 0,
    }


@pytest.mark.parametrize("amount", ["-0.1", "-9999", "NaN", "Infinity", "-Infinity", "", "invalid"])
def test_unavailable_rainfall_is_unknown_instead_of_dry(source: SourceTables, amount: str):
    source.observations.loc[1, "precip_mm"] = amount
    prepared = prepare_data(source)
    result = prepared.exposure("A1")
    assert prepared.quality["unavailable_rainfall_rows"] == 1
    assert result["wet_day_count"] is None
    assert result["wet_day_status"] == "no_complete_days"
    assert result["coverage"]["incomplete_days"] == 1


def test_absent_observation_makes_day_incomplete(source: SourceTables):
    source.observations.drop(index=1, inplace=True)
    result = prepare_data(source).exposure("A1")
    assert result["wet_day_count"] is None
    assert result["coverage"]["complete_days"] == 0


@pytest.mark.parametrize("station_id", ["UNKNOWN", ""])
def test_unknown_station_reference_cannot_supply_a_missing_reading(
    source: SourceTables, station_id: str,
):
    source.observations.loc[1, "station_id"] = station_id
    prepared = prepare_data(source)
    assert prepared.quality["unknown_or_missing_station_rows"] == 1
    assert prepared.exposure("A1")["wet_day_count"] is None


@pytest.mark.parametrize("timestamp", ["invalid", "2025-01-01T05:00:00", "2025-02-30T05:00:00Z"])
def test_invalid_or_naive_timestamp_cannot_complete_day(source: SourceTables, timestamp: str):
    source.observations.loc[1, "observed_at"] = timestamp
    prepared = prepare_data(source)
    assert prepared.quality["invalid_timestamp_rows"] == 1
    assert prepared.exposure("A1")["wet_day_count"] is None


def test_no_valid_timestamps_fails_at_startup(source: SourceTables, tmp_path: Path):
    source.observations["observed_at"] = "invalid"
    with pytest.raises(ValueError, match="No valid timezone-aware source timestamps"):
        with TestClient(create_app(write_source(source, tmp_path))):
            pass


@pytest.mark.parametrize("coordinate", ["NaN", "Infinity", "invalid"])
def test_invalid_asset_coordinate_returns_422(
    source: SourceTables, tmp_path: Path, coordinate: str,
):
    source.assets.loc[0, "x"] = coordinate
    with TestClient(create_app(write_source(source, tmp_path))) as client:
        response = client.get("/assets/A1/exposure")
    assert response.status_code == 422
    assert "Invalid source data" in response.json()["detail"]


def test_no_complete_days_serializes_metrics_as_json_null(source: SourceTables, tmp_path: Path):
    source.observations.loc[1, "precip_mm"] = ""
    with TestClient(create_app(write_source(source, tmp_path))) as client:
        response = client.get("/assets/A1/exposure")
    assert response.status_code == 200
    result = response.json()
    assert result["wet_day_count"] is None
    assert result["worst_three_day_precip_mm"] is None
    assert result["wet_day_status"] == "no_complete_days"
    assert result["three_day_status"] == "no_complete_three_day_window"
    assert result["coverage"] == {
        "complete_days": 0, "incomplete_days": 1, "eligible_three_day_windows": 0,
    }
    assert '"wet_day_count":null' in response.text
    assert '"worst_three_day_precip_mm":null' in response.text


@pytest.mark.parametrize("reason", ["invalid_coordinates", "not_yet_active"])
def test_no_eligible_station_returns_503(source: SourceTables, tmp_path: Path, reason: str):
    if reason == "invalid_coordinates":
        source.stations.loc[0, "lat"] = "91"
    else:
        source.stations.loc[0, "valid_from"] = "2025-01-02"
    with TestClient(create_app(write_source(source, tmp_path))) as client:
        response = client.get("/assets/A1/exposure")
    assert response.status_code == 503
    assert "No unambiguous station location" in response.json()["detail"]


def test_global_period_keeps_missing_days_for_stations_with_shorter_history(source: SourceTables):
    source.stations.loc[1] = source.stations.loc[0]
    source.stations.loc[1, "station_id"] = "S2"
    source.stations.loc[1, "lon"] = "15"
    source.observations.loc[4] = {
        "station_id": "S2", "observed_at": "2025-01-03T17:00:00Z",
        "precip_mm": "100", "temp_c": "0",
    }
    prepared = prepare_data(source)
    result = prepared.exposure("A1")
    assert prepared.start == date(2025, 1, 1)
    assert prepared.end == date(2025, 1, 3)
    assert result["station_id"] == "S1"
    assert result["wet_day_count"] == 1
    assert result["worst_three_day_precip_mm"] is None
    assert result["coverage"] == {
        "complete_days": 1, "incomplete_days": 2, "eligible_three_day_windows": 0,
    }
    assert prepared.summaries["S2"]["coverage"]["incomplete_days"] == 3


def test_repeated_requests_do_not_read_csvs_again(
    source: SourceTables, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    with TestClient(create_app(write_source(source, tmp_path))) as client:
        def unexpected_read(*args, **kwargs):
            pytest.fail("CSV input was read during a request after startup")

        monkeypatch.setattr(pd, "read_csv", unexpected_read)
        first = client.get("/assets/A1/exposure")
        second = client.get("/assets/A1/exposure")
        health = client.get("/health")
    assert first.status_code == second.status_code == health.status_code == 200
    assert first.json() == second.json()
    assert first.json()["wet_day_count"] == 1
