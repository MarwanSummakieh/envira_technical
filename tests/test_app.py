from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.main import create_app


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    tables = {
        "assets": "asset_id,address,x,y,asset_type,insured_value_dkk\nA1,Example,600000,6200000,residential,1000000\n",
        "stations": "station_id,station_name,lat,lon,valid_from,valid_to\nS1,Example,56,10,2025-01-01,\n",
        "observations": "station_id,observed_at,precip_mm,temp_c\nS1,2024-12-31T23:00:00Z,2.0,5.0\n",
    }
    for name, content in tables.items():
        (tmp_path / f"{name}.csv").write_text(content, encoding="utf-8")
    return tmp_path


def test_health_with_isolated_inputs(data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENVIRA_DATA_DIR", str(data_dir / "not-used"))
    app = create_app(data_dir)
    assert not hasattr(app.state, "prepared")
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert "A1" in app.state.prepared.asset_ids
        assert client.get("/assets/UNKNOWN/exposure").status_code == 404
    assert not hasattr(app.state, "prepared")


def test_environment_data_directory(data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENVIRA_DATA_DIR", str(data_dir))
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200


def test_frontend_is_served_from_the_same_app(data_dir: Path):
    with TestClient(create_app(data_dir)) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Rainfall exposure" in response.text


def test_missing_input_fails_at_startup(tmp_path: Path):
    app = create_app(tmp_path)
    with pytest.raises(ValueError, match="Cannot load required input.*assets.csv"):
        with TestClient(app):
            pass


def test_bad_schema_fails_at_startup(data_dir: Path):
    (data_dir / "observations.csv").write_text("station_id\nS1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required columns.*observed_at"):
        with TestClient(create_app(data_dir)):
            pass


def test_exposure_uses_fixture_rainfall(data_dir: Path):
    # Three local dates: 20, 10 and 30 mm; exactly two wet days and one 60 mm window.
    rows = ["station_id,observed_at,precip_mm,temp_c"]
    dates_and_amounts = [
        ("2024-12-31T23:00:00Z", "5"), ("2025-01-01T05:00:00Z", "5"),
        ("2025-01-01T11:00:00Z", "5"), ("2025-01-01T17:00:00Z", "5"),
        ("2025-01-01T23:00:00Z", "2.5"), ("2025-01-02T05:00:00Z", "2.5"),
        ("2025-01-02T11:00:00Z", "2.5"), ("2025-01-02T17:00:00Z", "2.5"),
        ("2025-01-02T23:00:00Z", "7.5"), ("2025-01-03T05:00:00Z", "7.5"),
        ("2025-01-03T11:00:00Z", "7.5"), ("2025-01-03T17:00:00Z", "7.5"),
    ]
    rows.extend(f"S1,{stamp},{amount},0" for stamp, amount in dates_and_amounts)
    (data_dir / "observations.csv").write_text("\n".join(rows), encoding="utf-8")
    with TestClient(create_app(data_dir)) as client:
        response = client.get("/assets/A1/exposure")
    assert response.status_code == 200
    result = response.json()
    assert result["station_id"] == "S1"
    assert result["distance_m"] > 0
    assert result["wet_day_count"] == 2
    assert result["worst_three_day_precip_mm"] == 60
    assert result["coverage"] == {"complete_days": 3, "incomplete_days": 0, "eligible_three_day_windows": 1}
