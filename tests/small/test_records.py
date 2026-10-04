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
        entity_records = await client.get("/entities/1/records")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "records": [
            {
                "id": 1,
                "entity_id": 1,
                "title": "Stored example",
                "body": "<p>Stored body</p>",
                "source_url": "/record/example-1",
                "published_at": "2026-09-19T00:00:00Z",
            }
        ],
        "pagination": {"limit": 20, "offset": 0, "total": 1},
    }
    assert entity_records.status_code == status.HTTP_200_OK
    assert entity_records.json() == {
        "records": [
            {
                "id": 1,
                "title": "Stored example",
                "body": "<p>Stored body</p>",
            }
        ]
    }
    engine.dispose()


@pytest.mark.anyio
@pytest.mark.small
async def test_development_app_lists_all_entity_fields() -> None:
    """The full entity endpoint returns every column, including inactive rows."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    first_created_at = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)
    first_updated_at = datetime(2026, 9, 2, 11, 0, 0, tzinfo=UTC)
    second_created_at = datetime(2026, 9, 3, 12, 0, 0, tzinfo=UTC)
    second_updated_at = datetime(2026, 9, 4, 13, 0, 0, tzinfo=UTC)
    with sessions.begin() as session:
        first_source = Source(name="source_a")
        second_source = Source(name="source_b")
        session.add_all([first_source, second_source])
        session.flush()
        session.add_all(
            [
                Entity(
                    source_id=first_source.id,
                    external_key="member-1",
                    name="First member",
                    is_active=True,
                    created_at=first_created_at,
                    updated_at=first_updated_at,
                ),
                Entity(
                    source_id=second_source.id,
                    external_key="member-2",
                    name="Second member",
                    is_active=False,
                    created_at=second_created_at,
                    updated_at=second_updated_at,
                ),
            ]
        )

    settings = Settings(
        environment="development",
        database_url=SecretStr("mysql+pymysql://db/collector"),
    )
    application = create_app(settings, sessions=sessions)
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/entities/all")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "entities": [
            {
                "id": 1,
                "source_id": 1,
                "external_key": "member-1",
                "name": "First member",
                "is_active": True,
                "created_at": "2026-09-01T10:00:00Z",
                "updated_at": "2026-09-02T11:00:00Z",
            },
            {
                "id": 2,
                "source_id": 2,
                "external_key": "member-2",
                "name": "Second member",
                "is_active": False,
                "created_at": "2026-09-03T12:00:00Z",
                "updated_at": "2026-09-04T13:00:00Z",
            },
        ]
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
