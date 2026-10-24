"""Maintenance controls survive application restarts and isolate source sites."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.collection import Base

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session


@pytest.fixture
def anyio_backend() -> str:
    """Exercise the API on asyncio."""
    return "asyncio"


@pytest.fixture
def control_sessions() -> Iterator[sessionmaker[Session]]:
    """Keep a local database across independently constructed applications."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    yield sessionmaker(engine)
    engine.dispose()


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
    assert response.status_code == 200
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
        assert response.status_code == 200
        assert response.json()["paused"] is False
        assert response.json()["next_check_at"] is None
