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
    assert not hasattr(app.state, "source_tables")
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert app.state.source_tables.assets.iloc[0].asset_id == "A1"
        assert client.get("/assets/A1/exposure").status_code == 404
    assert not hasattr(app.state, "source_tables")


def test_environment_data_directory(data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENVIRA_DATA_DIR", str(data_dir))
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200


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
