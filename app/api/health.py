"""Health endpoint."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

router = APIRouter()


class HealthResponse(BaseModel):
    """Public availability response."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"]


@router.get("/health", response_model=HealthResponse)
async def get_health() -> HealthResponse:
    """Report that the application process can serve requests."""
    return HealthResponse(status="ok")
