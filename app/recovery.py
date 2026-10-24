"""Composition root for standalone source recovery checks."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.scraping.recovery import ConfiguredRecoveryChecker
from app.services.control import RecoveryResult, recover_due_sites

if TYPE_CHECKING:
    from collections.abc import Callable

    import httpx

    from app.config import Settings
    from app.models.control import ControlRepository


def run_recovery_checks(
    *,
    settings: Settings,
    repository: ControlRepository,
    sleep: Callable[[float], None],
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    transport: httpx.BaseTransport | None = None,
) -> RecoveryResult:
    """Compose private bounded checks with durable maintenance decisions."""
    return recover_due_sites(
        checker=ConfiguredRecoveryChecker(settings, sleep=sleep, transport=transport),
        repository=repository,
        now=now,
    )
