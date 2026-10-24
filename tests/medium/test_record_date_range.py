"""HTTP contracts for complete publication-date range retrieval."""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.collection import Base, Entity, Record, Source

pytestmark = [pytest.mark.anyio, pytest.mark.medium]


@pytest.fixture
def anyio_backend() -> str:
    """Run requests on the asyncio backend."""
    return "asyncio"


@pytest.fixture
def application() -> Iterator[FastAPI]:
    """Supply more than one full page of records and exact date boundaries."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    with sessions.begin() as session:
        source = Source(name="example")
        session.add(source)
        session.flush()
        entities = [
            Entity(source_id=source.id, external_key="first", name="First author"),
            Entity(
                source_id=source.id,
                external_key="second",
                name="Second author",
                is_active=False,
            ),
        ]
        session.add_all(entities)
        session.flush()
        count = 105
        for number in range(1, count + 1):
            session.add(
                Record(
                    entity_id=entities[0 if number < count else 1].id,
                    external_key=f"record-{number}",
                    title=f"Article {number}",
                    body=f"<p>Body {number}</p>",
                    source_url=f"/articles/{number}",
                    published_at=datetime(2026, 10, 4, 12, tzinfo=UTC),
                ),
            )
        for key, published_at in (
            ("start", datetime(2026, 10, 1, tzinfo=UTC)),
            ("end", datetime(2026, 10, 7, 23, 59, 59, 999999, tzinfo=UTC)),
            ("before", datetime(2026, 9, 30, 23, 59, 59, 999999, tzinfo=UTC)),
            ("after", datetime(2026, 10, 8, tzinfo=UTC)),
        ):
            session.add(
                Record(
                    entity_id=entities[0].id,
                    external_key=key,
                    title=key,
                    body=f"<p>{key}</p>",
                    source_url=f"/articles/{key}",
                    published_at=published_at,
                ),
            )
    settings = Settings(
        environment="development",
        database_url=SecretStr("mysql+pymysql://db/collector"),
    )
    yield create_app(settings, sessions=sessions)
    engine.dispose()


async def test_date_range_returns_every_record_including_both_boundary_days(
    application: FastAPI,
) -> None:
    """A complete range includes bodies and never stops at the 100-record limit."""
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get(
            "/records/by-date", params={"from": "2026-10-01", "to": "2026-10-07"}
        )

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    expected_ids = [107, *range(105, 0, -1), 106]
    assert [record["id"] for record in payload["records"]] == expected_ids
    assert payload["records"][1] == {
        "id": 105,
        "entity_id": 2,
        "title": "Article 105",
        "body": "<p>Body 105</p>",
        "source_url": "/articles/105",
        "published_at": "2026-10-04T12:00:00Z",
    }
    assert set(payload) == {"records"}
