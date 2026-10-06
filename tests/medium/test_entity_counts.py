"""Local entity counts expose the exact stored collection checkpoint."""

from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.collection import Base, Entity, Record, Source


@pytest.fixture
def anyio_backend() -> str:
    """Run the local API contract on asyncio."""
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.medium
async def test_entity_list_counts_active_inactive_and_empty_histories() -> None:
    """Counts remain exact for filtered sources and members without records."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    with sessions.begin() as session:
        first = Source(name="source_a")
        second = Source(name="source_b")
        session.add_all([first, second])
        session.flush()
        active = Entity(source_id=first.id, external_key="7", name="Active author")
        inactive = Entity(
            source_id=second.id,
            external_key="8",
            name="Inactive author",
            is_active=False,
        )
        empty = Entity(source_id=second.id, external_key="9", name="Empty author")
        session.add_all([active, inactive, empty])
        session.flush()
        session.add_all(
            [
                Record(
                    entity_id=owner.id,
                    external_key=key,
                    title="Article",
                    body="<p>Body</p>",
                    source_url=f"/record/{key}",
                    published_at=datetime(2026, 9, 19, tzinfo=UTC),
                )
                for owner, key in [(active, "1"), (active, "2"), (inactive, "3")]
            ]
        )
    settings = Settings(
        environment="development",
        database_url=SecretStr("mysql+pymysql://db/collector"),
    )
    application = create_app(settings, sessions=sessions)
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        all_entities = (await client.get("/entities")).json()["entities"]
        filtered = (await client.get("/entities", params={"source_id": 2})).json()[
            "entities"
        ]
    assert [
        (row["name"], row["is_active"], row["record_count"]) for row in all_entities
    ] == [
        ("Active author", True, 2),
        ("Inactive author", False, 1),
        ("Empty author", True, 0),
    ]
    assert [(row["name"], row["record_count"]) for row in filtered] == [
        ("Inactive author", 1),
        ("Empty author", 0),
    ]
    engine.dispose()
