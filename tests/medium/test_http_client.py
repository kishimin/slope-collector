"""Bounded source HTTP client contract tests."""

import httpx
import pytest

from app.scraping.http_client import BoundedHttpClient, FetchPermanentError


def client(transport: httpx.BaseTransport, *, max_bytes: int = 1024) -> BoundedHttpClient:
    """Create an anonymous bounded client."""
    return BoundedHttpClient(
        base_url="https://source.example",
        user_agent="slope-collector-test/1.0 contact@example.invalid",
        connect_timeout_seconds=1,
        response_timeout_seconds=2,
        max_response_bytes=max_bytes,
        transport=transport,
    )


@pytest.mark.medium
def test_client_reads_bounded_html_from_approved_host() -> None:
    """An approved HTML response is returned as text."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<main>ok</main>",
            request=request,
        )
    )

    with client(transport) as http_client:
        assert http_client.get_html("/list") == "<main>ok</main>"


@pytest.mark.medium
@pytest.mark.parametrize(
    ("response_headers", "response_body"),
    [
        ({"content-type": "application/json"}, b"{}"),
        ({"content-type": "text/html"}, b"x" * 32),
    ],
)
def test_client_rejects_unapproved_response_contracts(
    response_headers: dict[str, str],
    response_body: bytes,
) -> None:
    """Unexpected media types and oversized responses fail closed."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers=response_headers,
            content=response_body,
            request=request,
        )
    )

    with client(transport, max_bytes=16) as http_client:
        with pytest.raises(FetchPermanentError):
            http_client.get_html("/list")


@pytest.mark.medium
def test_client_rejects_redirect_outside_approved_host_without_leaking_it() -> None:
    """Redirects cannot expand the configured outbound boundary."""
    sentinel = "private-redirect.example"

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"location": f"https://{sentinel}/content"},
            request=request,
        )

    with client(httpx.MockTransport(respond)) as http_client:
        with pytest.raises(FetchPermanentError) as error:
            http_client.get_html("/list")

    assert sentinel not in str(error.value)
