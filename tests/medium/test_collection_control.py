"""Maintenance controls survive application restarts and isolate source sites."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from app.models.control import Target
from app.repositories.control import SqlAlchemyControlRepository

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def anyio_backend() -> str:
    """Exercise the API on asyncio."""
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.medium
@pytest.mark.parametrize("environment", ["development", "production"])
async def test_manual_pause_survives_restart_and_resume_needs_no_probe(
    control_sessions: sessionmaker[Session], environment: str
) -> None:
    """An operator controls one site without affecting its archive counterpart."""
    settings = Settings.model_validate(
        {
            "environment": environment,
            "debug": False,
            "database_url": "mysql+pymysql://db/collector",
        }
    )
    application = create_app(settings, sessions=control_sessions)
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.post(
            "/collection-controls/source_a/official/pause",
            json={"resume_mode": "manual", "reason": "Maintenance"},
        )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["paused"] is True
    assert response.json()["reason"] == "Maintenance"
    assert response.json()["next_check_at"] is None

    restarted = create_app(settings, sessions=control_sessions)
    async with AsyncClient(
        transport=ASGITransport(app=restarted), base_url="http://test"
    ) as client:
        states = (await client.get("/collection-controls")).json()["controls"]
        by_target = {(state["source"], state["site"]): state for state in states}
        assert by_target["source_a", "official"]["paused"] is True
        assert by_target["source_a", "archive"]["paused"] is False
        response = await client.post("/collection-controls/source_a/official/resume")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["paused"] is False
        assert response.json()["next_check_at"] is None


@pytest.mark.medium
@pytest.mark.parametrize("succeeded", [False, True])
def test_due_recovery_checks_preserve_newer_operator_decisions(
    control_sessions: sessionmaker[Session], succeeded: bool
) -> None:
    """Only one worker claims a deadline and stale results cannot undo a pause."""
    repository = SqlAlchemyControlRepository(control_sessions)
    target = Target("source_a", "archive")
    now = datetime(2026, 10, 24, tzinfo=UTC)
    state = repository.pause(
        target, resume_mode="automatic", interval=60, reason=None, now=now
    )
    assert state.next_check_at == now + timedelta(hours=1)
    assert repository.claim_check(target, now) is None
    claimed = repository.claim_check(target, now + timedelta(hours=1))
    assert claimed is not None
    assert repository.claim_check(target, now + timedelta(hours=1)) is None
    repository.pause(target, resume_mode="manual", interval=60, reason=None, now=now)
    assert not repository.finish_check(
        target, claimed.revision, succeeded=succeeded, now=now
    )
    assert repository.get(target).paused is True
    assert repository.get(target).resume_mode == "manual"


@pytest.mark.anyio
@pytest.mark.medium
async def test_automatic_pause_requires_a_private_recovery_probe(
    control_sessions: sessionmaker[Session],
) -> None:
    """An operator cannot select automatic recovery without a usable check target."""
    settings = Settings.model_validate(
        {
            "database_url": "mysql+pymysql://db/collector",
            "collector_recovery_config_path": "",
        }
    )
    application = create_app(settings, sessions=control_sessions)
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.post(
            "/collection-controls/source_a/official/pause",
            json={"resume_mode": "automatic"},
        )
        assert response.status_code == status.HTTP_409_CONFLICT
        states = (await client.get("/collection-controls")).json()["controls"]
        assert all(not state["paused"] for state in states)
