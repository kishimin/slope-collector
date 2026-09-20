"""Bounded source HTTP client contract tests."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import httpx
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

from app.scraping.http_client import (
    BoundedHttpClient,
    FetchPermanentError,
    FetchTemporaryError,
    HttpLimits,
)


def client(
    transport: httpx.BaseTransport,
    *,
    max_bytes: int = 1024,
    clock: Callable[[], float] = time.monotonic,
) -> BoundedHttpClient:
    """Create an anonymous bounded client."""
    return BoundedHttpClient(
        base_url="https://source.example",
        user_agent="slope-collector-test/1.0 contact@example.invalid",
        limits=HttpLimits(
            connect_timeout_seconds=1,
            response_timeout_seconds=2,
            max_response_bytes=max_bytes,
        ),
        transport=transport,
        clock=clock,
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

    with (
        client(transport, max_bytes=16) as http_client,
        pytest.raises(FetchPermanentError),
    ):
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

    with (
        client(httpx.MockTransport(respond)) as http_client,
        pytest.raises(FetchPermanentError) as error,
    ):
        http_client.get_html("/list")

    assert sentinel not in str(error.value)


@pytest.mark.medium
def test_client_rejects_redirect_to_unapproved_port() -> None:
    """An approved hostname cannot expand the transport origin by port."""
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            302,
            headers={"location": "https://source.example:444/content"},
            request=request,
        )

    with (
        client(httpx.MockTransport(respond)) as http_client,
        pytest.raises(FetchPermanentError),
    ):
        http_client.get_html("/list")

    assert calls == 1


@pytest.mark.medium
def test_client_enforces_total_response_deadline() -> None:
    """Periodic small chunks cannot extend the whole-response deadline."""
    now = 0.0

    def clock() -> float:
        nonlocal now
        now += 0.8
        return now

    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"small chunks",
            request=request,
        )
    )

    with (
        client(transport, clock=clock) as http_client,
        pytest.raises(FetchTemporaryError),
    ):
        http_client.get_html("/list")
