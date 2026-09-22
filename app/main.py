"""Application lifecycle, HTTP routes, and the planned exposure contract."""
from contextlib import asynccontextmanager
from datetime import date
import logging
import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field

from app.data import load_source_tables


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
    """Contract only in Stage 2; no exposure route returns placeholder results."""

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
        application.state.source_tables = load_source_tables(directory)
        logger.info("Candidate CSVs loaded; schema checks passed (row cleaning pending)")
        try:
            yield
        finally:
            del application.state.source_tables

    application = FastAPI(title="Envira exposure service", lifespan=lifespan)

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return application
