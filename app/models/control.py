"""Maintenance state shared by operators, collectors, and recovery checks."""

from dataclasses import dataclass
from datetime import datetime  # noqa: TC003 - API dataclass schemas resolve this type.
from typing import Literal, Protocol

from app.config import (
    SourceKey,  # noqa: TC001 - API dataclass schemas resolve this type.
)

type SiteKind = Literal["official", "archive"]
type ResumeMode = Literal["manual", "automatic"]
SOURCE_KEYS: tuple[SourceKey, ...] = ("source_a", "source_b", "source_c")
SITE_KINDS: tuple[SiteKind, ...] = ("official", "archive")


@dataclass(frozen=True, slots=True)
class Target:
    """Identify a configured source site without revealing its location."""

    source: SourceKey
    site: SiteKind

    @property
    def key(self) -> str:
        """Return the stable persistence key."""
        return f"{self.source}:{self.site}"


TARGETS = tuple(Target(source, site) for source in SOURCE_KEYS for site in SITE_KINDS)


@dataclass(frozen=True, slots=True)
class ControlState:
    """Expose desired collection state, independently of process lifetime."""

    source: SourceKey
    site: SiteKind
    paused: bool = False
    resume_mode: ResumeMode = "manual"
    check_interval_minutes: int = 60
    reason: str | None = None
    next_check_at: datetime | None = None
    last_checked_at: datetime | None = None
    last_check_succeeded: bool | None = None
    last_check_error: str | None = None
    revision: str = ""


class ControlStorageError(RuntimeError):
    """Control storage is unavailable; collection must fail closed."""


class CollectionPausedError(Exception):
    """Stop before another outbound request without treating a pause as failure."""


class ControlRepository(Protocol):
    """Durable maintenance controls and compare-and-set recovery results."""

    def get(self, target: Target) -> ControlState:
        """Read the latest state from shared storage."""

    def pause(
        self,
        target: Target,
        *,
        resume_mode: ResumeMode,
        interval: int,
        reason: str | None,
        now: datetime,
    ) -> ControlState:
        """Replace a pause and invalidate any in-flight recovery result."""

    def resume(self, target: Target) -> ControlState:
        """Unconditionally release a pause without external requests."""

    def claim_check(self, target: Target, now: datetime) -> ControlState | None:
        """Claim one due recovery check across worker processes."""

    def finish_check(
        self, target: Target, revision: str, *, succeeded: bool, now: datetime
    ) -> bool:
        """Apply a result only if no newer operator action replaced its claim."""
