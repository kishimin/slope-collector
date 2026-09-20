"""Local record browsing contract tests."""

from datetime import UTC, datetime

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.collection import Base, Entity, Record, Source


@pytest.fixture
def anyio_backend() -> str:
    """Run the ASGI contract in one asyncio event loop."""
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.small
async def test_development_app_lists_stored_records() -> None:
    """A local user can confirm that a collected record was persisted."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    with sessions.begin() as session:
        source = Source(name="source_a")
        session.add(source)
        session.flush()
        entity = Entity(source_id=source.id, external_key="7", name="Example author")
        session.add(entity)
        session.flush()
        session.add(
            Record(
                entity_id=entity.id,
                external_key="example-1",
                title="Stored example",
                body="<p>Stored body</p>",
                source_url="/record/example-1",
                published_at=datetime(2026, 9, 19, tzinfo=UTC),
            )
        )

    settings = Settings(
        environment="development",
        database_url=SecretStr("mysql+pymysql://db/collector"),
    )
    application = create_app(settings, sessions=sessions)
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/records")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "records": [
            {
                "id": 1,
                "entity_id": 1,
                "title": "Stored example",
                "source_url": "/record/example-1",
                "published_at": "2026-09-19T00:00:00Z",
            }
        ],
        "pagination": {"limit": 20, "offset": 0, "total": 1},
    }
    engine.dispose()


@pytest.mark.anyio
@pytest.mark.small
async def test_production_app_does_not_publish_stored_records() -> None:
    """A production application never exposes locally collected records."""
    settings = Settings(
        environment="production",
        debug=False,
        database_url=SecretStr("mysql+pymysql://db/collector"),
    )
    application = create_app(settings)
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/records")

    assert response.status_code == status.HTTP_404_NOT_FOUND
