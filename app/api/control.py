"""Internal maintenance API for the authenticated GUI server."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.config import SourceKey  # noqa: TC001 - FastAPI resolves route annotations.
from app.models.control import TARGETS, ControlState, ResumeMode, SiteKind, Target
from app.scraping.recovery import load_recovery_probe

if TYPE_CHECKING:
    from app.models.control import ControlRepository


class PauseRequest(BaseModel):
    """Bound operator input without accepting external URLs or config paths."""

    model_config = ConfigDict(extra="forbid")
    resume_mode: ResumeMode
    check_interval_minutes: int = Field(default=60, ge=1, le=1440, strict=True)
    reason: str | None = Field(default=None, max_length=255)


def create_control_router(
    repository: ControlRepository, recovery_config_path: str
) -> APIRouter:
    """Expose maintenance controls in every environment on the internal API."""
    router = APIRouter(prefix="/collection-controls", tags=["collection-controls"])

    @router.get("")
    async def list_controls() -> dict[str, list[ControlState]]:
        return {"controls": [repository.get(target) for target in TARGETS]}

    @router.post("/{source}/{site}/pause")
    async def pause(
        source: SourceKey, site: SiteKind, body: PauseRequest
    ) -> ControlState:
        if body.resume_mode == "automatic":
            load_recovery_probe(recovery_config_path, Target(source, site))
        return repository.pause(
            Target(source, site),
            resume_mode=body.resume_mode,
            interval=body.check_interval_minutes,
            reason=body.reason,
            now=datetime.now(UTC),
        )

    @router.post("/{source}/{site}/resume")
    async def resume(source: SourceKey, site: SiteKind) -> ControlState:
        return repository.resume(Target(source, site))

    return router
