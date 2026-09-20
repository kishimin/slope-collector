"""Acceptance contract for the development-only read API."""

# Acceptance assertions intentionally describe the externally observable contract.
# ruff: noqa: INP001, S101

from datetime import UTC, datetime

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.collection import Asset, Base, Entity, Record, Source


@pytest.fixture
def anyio_backend() -> str:
    """Run the HTTP contract in one asyncio event loop."""
    return "asyncio"


@pytest.fixture
def application() -> object:
    """Provide a local development API with anonymous representative data."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    with sessions.begin() as session:
        first_source = Source(name="source_a")
        second_source = Source(name="source_b")
        session.add_all([first_source, second_source])
        session.flush()
        first_entity = Entity(
            source_id=first_source.id,
            external_key="entity-1",
            name="Example author A",
        )
        second_entity = Entity(
            source_id=second_source.id,
            external_key="entity-2",
            name="Example author B",
            is_active=False,
        )
        session.add_all([first_entity, second_entity])
        session.flush()
        older = Record(
            entity_id=first_entity.id,
            external_key="record-1",
            title="Older example",
            body="<p>Older body</p>",
            source_url="/records/record-1",
            published_at=datetime(2026, 1, 10, 8, 0, tzinfo=UTC),
        )
        newer = Record(
            entity_id=second_entity.id,
            external_key="record-2",
            title="Newer example",
            body="<p>Newer body</p>",
            source_url="/records/record-2",
            published_at=datetime(2026, 2, 20, 9, 30, tzinfo=UTC),
        )
        session.add_all([older, newer])
        session.flush()
        session.add(
            Asset(
                record_id=newer.id,
                source_url="/assets/example.png",
                position=0,
                alt_text="Example image",
            )
        )

    settings = Settings(
        environment="development",
        database_url=SecretStr("mysql+pymysql://db/collector"),
    )
    return create_app(settings, sessions=sessions)


@pytest.mark.anyio
@pytest.mark.medium
async def test_local_user_can_browse_sources_entities_and_record_details(
    application: object,
) -> None:
    """The five read endpoints expose their documented successful responses."""
    transport = ASGITransport(app=application)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        sources = await client.get("/sources")
        entities = await client.get("/entities")
        entity = await client.get("/entities/1")
        records = await client.get("/records")
        record = await client.get("/records/2")

    assert sources.status_code == status.HTTP_200_OK
    assert sources.json() == {
        "sources": [{"id": 1, "name": "source_a"}, {"id": 2, "name": "source_b"}]
    }
    assert entities.status_code == status.HTTP_200_OK
    assert entities.json() == {
        "entities": [
            {"id": 1, "source_id": 1, "name": "Example author A", "is_active": True},
            {"id": 2, "source_id": 2, "name": "Example author B", "is_active": False},
        ]
    }
    assert entity.status_code == status.HTTP_200_OK
    assert entity.json() == {
        "id": 1,
        "source_id": 1,
        "name": "Example author A",
        "is_active": True,
    }
    assert records.status_code == status.HTTP_200_OK
    assert records.json() == {
        "records": [
            {
                "id": 2,
                "entity_id": 2,
                "title": "Newer example",
                "source_url": "/records/record-2",
                "published_at": "2026-02-20T09:30:00Z",
            },
            {
                "id": 1,
                "entity_id": 1,
                "title": "Older example",
                "source_url": "/records/record-1",
                "published_at": "2026-01-10T08:00:00Z",
            },
        ],
        "pagination": {"limit": 20, "offset": 0, "total": 2},
    }
    assert record.status_code == status.HTTP_200_OK
    assert record.json() == {
        "id": 2,
        "entity_id": 2,
        "title": "Newer example",
        "body": "<p>Newer body</p>",
        "source_url": "/records/record-2",
        "published_at": "2026-02-20T09:30:00Z",
        "assets": [{"id": 1, "source_url": "/assets/example.png", "position": 0}],
    }


@pytest.mark.anyio
@pytest.mark.medium
async def test_local_user_can_filter_and_page_record_lists(application: object) -> None:
    """Filters are exact, inclusive, and pagination reports the filtered total."""
    transport = ASGITransport(app=application)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        entities = await client.get("/entities", params={"source_id": 2})
        records = await client.get(
            "/records",
            params={
                "entity_id": 1,
                "from": "2026-01-10",
                "to": "2026-01-10",
                "limit": 1,
                "offset": 0,
            },
        )
        empty_page = await client.get("/records", params={"limit": 1, "offset": 2})

    assert entities.json() == {
        "entities": [
            {"id": 2, "source_id": 2, "name": "Example author B", "is_active": False}
        ]
    }
    assert records.json()["records"] == [
        {
            "id": 1,
            "entity_id": 1,
            "title": "Older example",
            "source_url": "/records/record-1",
            "published_at": "2026-01-10T08:00:00Z",
        }
    ]
    assert records.json()["pagination"] == {"limit": 1, "offset": 0, "total": 1}
    assert empty_page.json() == {
        "records": [],
        "pagination": {"limit": 1, "offset": 2, "total": 2},
    }


@pytest.mark.anyio
@pytest.mark.medium
async def test_local_user_receives_common_errors(application: object) -> None:
    """Missing resources and invalid queries use the documented error envelope."""
    transport = ASGITransport(app=application)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing_entity = await client.get("/entities/999")
        missing_record = await client.get("/records/999")
        invalid_limit = await client.get("/records", params={"limit": 101})
        invalid_offset = await client.get("/records", params={"offset": -1})
        invalid_range = await client.get(
            "/records", params={"from": "2026-02-01", "to": "2026-01-01"}
        )

    for response in (missing_entity, missing_record):
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json() == {
            "code": "NOT_FOUND",
            "message": "Requested resource does not exist.",
        }
    for response, field in ((invalid_limit, "limit"), (invalid_offset, "offset")):
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert response.json()["code"] == "VALIDATION_ERROR"
        assert response.json()["message"] == "Request validation failed."
        assert response.json()["errors"][0]["field"] == field
    assert invalid_range.status_code == status.HTTP_400_BAD_REQUEST
    assert invalid_range.json() == {
        "code": "BAD_REQUEST",
        "message": "The start date must not be after the end date.",
    }
