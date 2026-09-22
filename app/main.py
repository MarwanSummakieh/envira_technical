"""Application lifecycle, HTTP routes and exposure response contract."""
from contextlib import asynccontextmanager
from datetime import date
import logging
import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.data import (
    ConflictingAssetError, InvalidAssetError, NoEligibleStationError,
    load_source_tables, prepare_data,
)


logger = logging.getLogger(__name__)


class AnalysisPeriod(BaseModel):
    start: date
    end: date
    timezone: Literal["Europe/Copenhagen"] = "Europe/Copenhagen"


class Coverage(BaseModel):
    complete_days: int = Field(ge=0)
    incomplete_days: int = Field(ge=0)
    eligible_three_day_windows: int = Field(ge=0)


class ExposureResponse(BaseModel):
    """Rainfall metrics describe complete observed days, not flood-loss probability."""

    model_config = ConfigDict(allow_inf_nan=False)
    asset_id: str
    station_id: str
    distance_m: float = Field(ge=0)
    wet_day_count: int | None = Field(ge=0)
    worst_three_day_precip_mm: float | None = Field(ge=0)
    wet_day_status: Literal["available", "no_complete_days"]
    three_day_status: Literal["available", "no_complete_three_day_window"]
    analysis_period: AnalysisPeriod
    coverage: Coverage


def create_app(data_dir: str | Path | None = None) -> FastAPI:
    """Explicit argument overrides ENVIRA_DATA_DIR; otherwise use ./data."""
    directory = Path(data_dir if data_dir is not None else os.environ.get("ENVIRA_DATA_DIR", "data"))

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.prepared = prepare_data(load_source_tables(directory))
        logger.info("Candidate CSVs prepared for exposure requests")
        try:
            yield
        finally:
            del application.state.prepared

    application = FastAPI(title="Envira exposure service", lifespan=lifespan)

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/assets/{asset_id}/exposure", response_model=ExposureResponse)
    def exposure(asset_id: str) -> dict:
        try:
            return application.state.prepared.exposure(asset_id)
        except KeyError as exc:
            raise HTTPException(404, "Unknown asset") from exc
        except ConflictingAssetError as exc:
            raise HTTPException(409, str(exc)) from exc
        except InvalidAssetError as exc:
            raise HTTPException(422, str(exc)) from exc
        except NoEligibleStationError as exc:
            raise HTTPException(503, str(exc)) from exc

    return application
