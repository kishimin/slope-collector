"""Recovery orchestration that preserves newer operator maintenance decisions."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.models.control import TARGETS
from app.scraping.recovery import (
    RecoveryCancelledError,
    load_recovery_probe,
    probe_site,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    import httpx

    from app.config import Settings
    from app.models.control import ControlRepository, Target

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    """Sanitized counts from a standalone recovery pass."""

    checked: int = 0
    resumed: int = 0
    failed: int = 0


def run_recovery_checks(
    *,
    settings: Settings,
    repository: ControlRepository,
    sleep: Callable[[float], None],
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    transport: httpx.BaseTransport | None = None,
) -> RecoveryResult:
    """Check due automatic pauses once and release only the claimed decision."""
    checked = resumed = failed = 0
    for target in TARGETS:
        claim = repository.claim_check(target, now())
        if claim is None:
            continue
        checked += 1
        claimed_revision = claim.revision

        def authorize_request(
            requested: Target, target: Target = target, revision: str = claimed_revision
        ) -> None:
            current = repository.get(requested)
            if requested == target:
                allowed = (
                    current.paused
                    and current.resume_mode == "automatic"
                    and current.revision == revision
                )
            else:
                allowed = not current.paused
            if not allowed:
                raise RecoveryCancelledError

        try:
            probe = load_recovery_probe(
                settings.collector_recovery_config_path.get_secret_value(), target
            )
            probe_site(
                settings,
                probe,
                authorize_request=authorize_request,
                sleep=sleep,
                transport=transport,
            )
        except (ValueError, RuntimeError, KeyError, RecoveryCancelledError) as error:
            succeeded = False
            LOGGER.warning(
                "recovery check failed target=%s exception=%s",
                target.key,
                type(error).__name__,
            )
        else:
            succeeded = True
        applied = repository.finish_check(
            target, claim.revision, succeeded=succeeded, now=now()
        )
        resumed += int(applied and succeeded)
        failed += int(applied and not succeeded)
        LOGGER.info(
            "recovery check completed target=%s succeeded=%s applied=%s",
            target.key,
            succeeded,
            applied,
        )
    return RecoveryResult(checked=checked, resumed=resumed, failed=failed)
