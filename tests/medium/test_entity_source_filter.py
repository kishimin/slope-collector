"""Entity filters distinguish missing sources from empty source collections."""

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.collection import Base, Entity, Source


@pytest.fixture
def anyio_backend() -> str:
    """Use asyncio for the local API contract."""
    return "asyncio"


@pytest.mark.medium
@pytest.mark.anyio
@pytest.mark.parametrize(
    ("source_id", "expected_status"),
    [
        ("2", 404),
        ("999999", 404),
        ("3", 200),
        ("1", 200),
        (None, 200),
        ("0", 422),
        ("-1", 422),
        ("invalid", 422),
    ],
)
async def test_entity_filter_respects_source_existence(
    source_id: str | None, expected_status: int
) -> None:
    """Only a registered source can yield a successful filtered collection."""
    engine = create_engine("sqlite://")
    try:
        Base.metadata.create_all(engine)
        sessions = sessionmaker(engine)
        with sessions.begin() as session:
            session.add_all(
                [Source(id=1, name="populated"), Source(id=3, name="empty")]
            )
            session.flush()
            session.add(
                Entity(id=1, source_id=1, external_key="author-1", name="Author")
            )
        settings = Settings(
            environment="development",
            database_url=SecretStr("mysql+pymysql://db/collector"),
        )
        application = create_app(settings, sessions=sessions)
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            params = {} if source_id is None else {"source_id": source_id}
            response = await client.get("/entities", params=params)

        assert response.status_code == expected_status
        if expected_status == status.HTTP_404_NOT_FOUND:
            assert response.json() == {
                "code": "NOT_FOUND",
                "message": "Requested resource does not exist.",
            }
        elif expected_status == status.HTTP_422_UNPROCESSABLE_CONTENT:
            assert response.json()["code"] == "VALIDATION_ERROR"
            assert response.json()["errors"][0]["field"] == "source_id"
        else:
            expected_entities = (
                []
                if source_id == "3"
                else [
                    {
                        "id": 1,
                        "source_id": 1,
                        "name": "Author",
                        "is_active": True,
                    }
                ]
            )
            assert response.json() == {"entities": expected_entities}
    finally:
        engine.dispose()
