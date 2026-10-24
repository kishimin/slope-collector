"""SQLAlchemy maintenance storage with serialized writes and check claims."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.models.collection import CollectionControl
from app.models.control import ControlState, ControlStorageError

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

    from app.models.control import ResumeMode, Target


class SqlAlchemyControlRepository:
    """Keep each read fresh and prevent stale checks from releasing new pauses."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        """Use the same database as the collector checkpoints."""
        self._sessions = sessions

    @contextmanager
    def _transaction(self) -> Iterator[Session]:
        try:
            with self._sessions.begin() as session:
                yield session
        except SQLAlchemyError:
            message = "collection control storage is unavailable"
            raise ControlStorageError(message) from None

    def get(self, target: Target) -> ControlState:
        """Read current state without caching it in a collector process."""
        with self._transaction() as session:
            return _state(target, session.get(CollectionControl, target.key))

    @staticmethod
    def _locked(session: Session, target: Target) -> CollectionControl:
        row = session.get(CollectionControl, target.key, with_for_update=True)
        if row is None:
            try:
                with session.begin_nested():
                    session.add(CollectionControl(target=target.key))
                    session.flush()
            except IntegrityError:
                # Another first-time operator can create the same site concurrently.
                pass
            row = session.get(CollectionControl, target.key, with_for_update=True)
        if row is None:
            message = "collection control state could not be initialized"
            raise ControlStorageError(message)
        return row

    def pause(
        self,
        target: Target,
        *,
        resume_mode: ResumeMode,
        interval: int,
        reason: str | None,
        now: datetime,
    ) -> ControlState:
        """Persist a new operator decision and its next recovery deadline."""
        with self._transaction() as session:
            row = self._locked(session, target)
            row.paused = True
            row.resume_mode = resume_mode
            row.check_interval_minutes = interval
            row.reason = reason
            row.revision = str(uuid4())
            row.last_checked_at = None
            row.last_check_succeeded = None
            row.last_check_error = None
            row.next_check_at = (
                _naive(now) + timedelta(minutes=interval)
                if resume_mode == "automatic"
                else None
            )
            return _state(target, row)

    def resume(self, target: Target) -> ControlState:
        """Release a pause without testing the external site."""
        with self._transaction() as session:
            row = self._locked(session, target)
            row.paused = False
            row.next_check_at = None
            row.revision = str(uuid4())
            return _state(target, row)

    def claim_check(self, target: Target, now: datetime) -> ControlState | None:
        """Atomically reserve a due check before sending external requests."""
        with self._transaction() as session:
            row = session.get(CollectionControl, target.key)
            if row is None:
                return None
            revision = str(uuid4())
            result = session.connection().execute(
                update(CollectionControl)
                .where(
                    CollectionControl.target == target.key,
                    CollectionControl.paused.is_(True),
                    CollectionControl.resume_mode == "automatic",
                    CollectionControl.next_check_at <= _naive(now),
                    CollectionControl.revision == row.revision,
                )
                .values(
                    revision=revision,
                    next_check_at=_naive(now)
                    + timedelta(minutes=row.check_interval_minutes),
                )
            )
            if not result.rowcount:
                return None
            session.refresh(row)
            return _state(target, row)

    def finish_check(
        self, target: Target, revision: str, *, succeeded: bool, now: datetime
    ) -> bool:
        """Discard results superseded by a manual action or another claim."""
        with self._transaction() as session:
            row = session.get(CollectionControl, target.key)
            if row is None:
                return False
            result = session.connection().execute(
                update(CollectionControl)
                .where(
                    CollectionControl.target == target.key,
                    CollectionControl.revision == revision,
                    CollectionControl.paused.is_(True),
                    CollectionControl.resume_mode == "automatic",
                )
                .values(
                    paused=not succeeded,
                    last_checked_at=_naive(now),
                    last_check_succeeded=succeeded,
                    last_check_error=None if succeeded else "recovery check failed",
                    next_check_at=None
                    if succeeded
                    else _naive(now) + timedelta(minutes=row.check_interval_minutes),
                    revision=str(uuid4()),
                )
            )
            return bool(result.rowcount)


def _naive(value: datetime) -> datetime:
    """Store UTC explicitly because MySQL DATETIME has no timezone support."""
    return value.astimezone(UTC).replace(tzinfo=None)


def _aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value is not None else None


def _state(target: Target, row: CollectionControl | None) -> ControlState:
    if row is None:
        return ControlState(target.source, target.site)
    mode: ResumeMode = "automatic" if row.resume_mode == "automatic" else "manual"
    return ControlState(
        source=target.source,
        site=target.site,
        paused=row.paused,
        resume_mode=mode,
        check_interval_minutes=row.check_interval_minutes,
        reason=row.reason,
        next_check_at=_aware(row.next_check_at),
        last_checked_at=_aware(row.last_checked_at),
        last_check_succeeded=row.last_check_succeeded,
        last_check_error=row.last_check_error,
        revision=row.revision,
    )
