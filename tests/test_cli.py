import json
from pathlib import Path

import pytest

from app.cli import main


@pytest.fixture
def cli_data(tmp_path: Path) -> Path:
    tables = {
        "assets": (
            "asset_id,address,x,y,asset_type,insured_value_dkk\n"
            "A1,Example,600000,6200000,residential,1000000\n"
        ),
        "stations": (
            "station_id,station_name,lat,lon,valid_from,valid_to\n"
            "S1,Example,56,10,2025-01-01,\n"
        ),
        "observations": (
            "station_id,observed_at,precip_mm,temp_c\n"
            "S1,2024-12-31T23:00:00Z,2,5\n"
            "S1,2025-01-01T05:00:00Z,3,5\n"
            "S1,2025-01-01T11:00:00Z,5,5\n"
            "S1,2025-01-01T17:00:00Z,10,5\n"
        ),
    }
    for name, content in tables.items():
        (tmp_path / f"{name}.csv").write_text(content, encoding="utf-8")
    return tmp_path


def test_cli_prints_hand_calculated_json(cli_data: Path, capsys: pytest.CaptureFixture[str]):
    assert main(["A1", "--data-dir", str(cli_data)]) == 0
    captured = capsys.readouterr()
    response = json.loads(captured.out)
    assert captured.err == ""
    assert response["asset_id"] == "A1"
    assert response["station_id"] == "S1"
    assert response["distance_m"] >= 0
    assert response["wet_day_count"] == 1  # 2 + 3 + 5 + 10 = 20 mm.
    assert response["worst_three_day_precip_mm"] is None
    assert response["wet_day_status"] == "available"
    assert response["three_day_status"] == "no_complete_three_day_window"
    assert response["analysis_period"] == {
        "start": "2025-01-01", "end": "2025-01-01", "timezone": "Europe/Copenhagen",
    }
    assert response["coverage"] == {
        "complete_days": 1, "incomplete_days": 0, "eligible_three_day_windows": 0,
    }


def test_cli_unknown_asset_returns_error_without_json(cli_data: Path, capsys: pytest.CaptureFixture[str]):
    assert main(["missing", "--data-dir", str(cli_data)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Unknown asset missing" in captured.err


def test_cli_missing_data_directory_returns_helpful_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    assert main(["A1", "--data-dir", str(tmp_path / "missing")]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Cannot load required input" in captured.err
    assert "assets.csv" in captured.err


def test_cli_environment_default_and_explicit_directory_precedence(
    cli_data: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
):
    monkeypatch.setenv("ENVIRA_DATA_DIR", str(cli_data))
    assert main(["A1"]) == 0
    assert json.loads(capsys.readouterr().out)["wet_day_count"] == 1
    monkeypatch.setenv("ENVIRA_DATA_DIR", str(cli_data / "missing"))
    assert main(["A1", "--data-dir", str(cli_data)]) == 0
    assert json.loads(capsys.readouterr().out)["wet_day_count"] == 1


def test_cli_conflicting_asset_returns_domain_error(cli_data: Path, capsys: pytest.CaptureFixture[str]):
    with (cli_data / "assets.csv").open("a", encoding="utf-8") as stream:
        stream.write("A1,Another address,600000,6200000,residential,1000000\n")
    assert main(["A1", "--data-dir", str(cli_data)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Conflicting records for asset A1" in captured.err
