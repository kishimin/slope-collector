"""Health endpoint contract tests."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


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

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
