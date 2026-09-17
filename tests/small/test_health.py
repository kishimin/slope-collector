"""Health endpoint contract tests."""

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.config import Settings
from app.main import app, create_app


@pytest.fixture
def anyio_backend() -> str:
    """Run the ASGI contract in one asyncio event loop."""
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.small
async def test_health_returns_service_status() -> None:
    """The health endpoint reports availability without internal details."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
@pytest.mark.small
async def test_production_app_does_not_publish_api_docs() -> None:
    """Production does not expose internal API discovery endpoints."""
    settings = Settings(
        environment="production",
        debug=False,
        database_url=SecretStr("mysql+pymysql://db/collector"),
    )
    production_app = create_app(settings)
    transport = ASGITransport(app=production_app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/docs")

    assert response.status_code == status.HTTP_404_NOT_FOUND
