"""HTTP contracts for complete publication-date range retrieval."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.collection import Base, Entity, Record, Source

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import Literal

pytestmark = [pytest.mark.anyio, pytest.mark.medium]


@pytest.fixture
def anyio_backend() -> str:
    """Run requests on the asyncio backend."""
    return "asyncio"


@pytest.fixture
def application() -> Iterator[FastAPI]:
    """Supply UTC records at the exact boundaries of Japanese calendar dates."""
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
            Entity(source_id=source.id, external_key="empty", name="Empty author"),
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
            ("start", datetime(2026, 9, 30, 15, tzinfo=UTC)),
            ("end", datetime(2026, 10, 7, 14, 59, 59, 999999, tzinfo=UTC)),
            ("before", datetime(2026, 9, 30, 14, 59, 59, 999999, tzinfo=UTC)),
            ("after", datetime(2026, 10, 7, 15, tzinfo=UTC)),
            ("new-year-start", datetime(2025, 12, 31, 15, tzinfo=UTC)),
            ("new-year-end", datetime(2026, 1, 1, 14, 59, 59, 999999, tzinfo=UTC)),
            ("before-new-year", datetime(2025, 12, 31, 14, 59, 59, 999999, tzinfo=UTC)),
            ("after-new-year", datetime(2026, 1, 1, 15, tzinfo=UTC)),
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


async def test_entity_records_return_every_matching_record_with_japanese_dates(
    application: FastAPI,
) -> None:
    """Both JST boundaries are inclusive and no matching articles are truncated."""
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get(
            "/entities/1/records", params={"from": "2026-10-01", "to": "2026-10-07"}
        )

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert [record["id"] for record in payload["records"]] == [
        107,
        *range(104, 0, -1),
        106,
    ]
    assert payload["records"][1] == {
        "id": 104,
        "title": "Article 104",
        "body": "<p>Body 104</p>",
    }
    assert set(payload) == {"records"}


@pytest.mark.parametrize(
    ("parameters", "expected_ids"),
    [
        ({}, [109, 107, *range(104, 0, -1), 106, 108, 113, 111, 110, 112]),
        ({"from": "2026-10-01"}, [109, 107, *range(104, 0, -1), 106]),
        ({"to": "2026-10-07"}, [107, *range(104, 0, -1), 106, 108, 113, 111, 110, 112]),
        ({"from": "2026-10-07"}, [109, 107]),
        ({"to": "2026-10-01"}, [106, 108, 113, 111, 110, 112]),
        ({"from": "2026-10-01", "to": "2026-10-01"}, [106]),
        ({"from": "2026-10-07", "to": "2026-10-07"}, [107]),
        ({"from": "2026-10-02", "to": "2026-10-03"}, []),
        ({"from": "9999-12-31", "to": "9999-12-31"}, []),
        ({"from": "9999-12-31"}, []),
        ({"to": "0001-01-01"}, []),
        ({"from": "2026-01-01", "to": "2026-01-01"}, [111, 110]),
    ],
)
async def test_entity_record_dates_are_independently_optional(
    application: FastAPI, parameters: dict[str, str], expected_ids: list[int]
) -> None:
    """Missing bounds leave that side open while supplied dates use Japanese days."""
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get("/entities/1/records", params=parameters)

    assert response.status_code == status.HTTP_200_OK
    assert [record["id"] for record in response.json()["records"]] == expected_ids


@pytest.mark.parametrize(
    ("parameters", "expected_status", "expected_code"),
    [
        ({"from": "2026-02-30"}, 422, "VALIDATION_ERROR"),
        ({"to": "invalid"}, 422, "VALIDATION_ERROR"),
        ({"from": "2026-10-08", "to": "2026-10-01"}, 400, "BAD_REQUEST"),
        ({"from": "0001-01-01"}, 400, "BAD_REQUEST"),
    ],
)
async def test_entity_record_range_rejects_invalid_bounds(
    application: FastAPI,
    parameters: dict[str, str],
    expected_status: int,
    expected_code: str,
) -> None:
    """Malformed, reversed and unrepresentable bounds use common API errors."""
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get("/entities/1/records", params=parameters)

    assert response.status_code == expected_status
    assert response.json()["code"] == expected_code


@pytest.mark.parametrize("parameters", [{}, {"from": "2026-10-01", "to": "2026-10-07"}])
async def test_entity_record_dates_preserve_author_scope(
    application: FastAPI, parameters: dict[str, str]
) -> None:
    """Inactive authors' stored records remain readable within their own scope."""
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get("/entities/2/records", params=parameters)

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "records": [{"id": 105, "title": "Article 105", "body": "<p>Body 105</p>"}]
    }


async def test_unknown_and_empty_entities_keep_distinct_responses(
    application: FastAPI,
) -> None:
    """Unknown entities return 404; existing empty entities return an empty list."""
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        missing = await client.get(
            "/entities/999/records", params={"from": "2026-10-01"}
        )
        empty = await client.get("/entities/3/records", params={"to": "2026-10-07"})
        invalid = await client.get("/entities/0/records")

    assert missing.status_code == status.HTTP_404_NOT_FOUND
    assert missing.json()["code"] == "NOT_FOUND"
    assert empty.status_code == status.HTTP_200_OK
    assert empty.json() == {"records": []}
    assert invalid.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_record_range_is_integrated_into_the_existing_route(
    application: FastAPI,
) -> None:
    """The public schema exposes optional bounds on one existing complete-read route."""
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get("/openapi.json")

    schema = response.json()
    assert "/records/by-date" not in schema["paths"]
    parameters = schema["paths"]["/entities/{entity_id}/records"]["get"]["parameters"]
    for name in ("from", "to"):
        parameter = next(
            parameter for parameter in parameters if parameter["name"] == name
        )
        assert parameter["required"] is False
        assert "Asia/Tokyo" in parameter["description"]


async def test_existing_record_list_still_paginates(application: FastAPI) -> None:
    """Adding complete retrieval does not change existing list or detail URLs."""
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        first_page = await client.get(
            "/records", params={"from": "2026-10-01", "to": "2026-10-07"}
        )
        last_page = await client.get(
            "/records",
            params={
                "from": "2026-10-01",
                "to": "2026-10-07",
                "limit": 100,
                "offset": 100,
            },
        )
        detail = await client.get("/records/105")

    assert first_page.status_code == status.HTTP_200_OK
    assert first_page.json()["pagination"] == {"limit": 20, "offset": 0, "total": 107}
    assert len(first_page.json()["records"]) == first_page.json()["pagination"]["limit"]
    assert last_page.json()["pagination"] == {"limit": 100, "offset": 100, "total": 107}
    assert [record["id"] for record in last_page.json()["records"]] == [
        7,
        6,
        5,
        4,
        3,
        2,
        1,
    ]
    assert detail.status_code == status.HTTP_200_OK
    assert detail.json()["body"] == "<p>Body 105</p>"


@pytest.mark.parametrize("environment", ["production", "test"])
async def test_entity_record_dates_are_development_only(
    environment: Literal["production", "test"],
) -> None:
    """Optional dates do not expand the read API's environment boundary."""
    settings = Settings(
        environment=environment,
        debug=False,
        database_url=SecretStr("mysql+pymysql://db/collector"),
    )
    application = create_app(settings)
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get(
            "/entities/1/records", params={"from": "2026-10-01", "to": "2026-10-07"}
        )

    assert response.status_code == status.HTTP_404_NOT_FOUND
