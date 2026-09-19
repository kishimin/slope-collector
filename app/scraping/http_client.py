"""Bounded HTTP access for approved collection sources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self
from urllib.parse import urljoin, urlsplit

import httpx

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import TracebackType

MAX_REDIRECTS = 5
TOO_MANY_REQUESTS = 429
SERVER_ERROR_START = 500
SERVER_ERROR_END = 600


@dataclass(frozen=True, slots=True)
class HttpLimits:
    """Transport and response limits for one source client."""

    connect_timeout_seconds: float
    response_timeout_seconds: float
    max_response_bytes: int


class FetchTemporaryError(RuntimeError):
    """A request may succeed when retried later."""


class FetchPermanentError(RuntimeError):
    """A response violates the approved collection contract."""


class BoundedHttpClient:
    """Fetch HTML without leaving a configured HTTPS host boundary."""

    def __init__(
        self,
        *,
        base_url: str,
        user_agent: str,
        limits: HttpLimits,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Create a client with explicit transport and response bounds."""
        parsed = urlsplit(base_url)
        if parsed.scheme != "https" or parsed.hostname is None:
            message = "source transport configuration is invalid"
            raise ValueError(message)
        if not user_agent.strip():
            message = "collector user agent is required"
            raise ValueError(message)
        self._base_url = base_url
        self._approved_host = parsed.hostname.lower()
        self._approved_port = parsed.port or 443
        self._max_response_bytes = limits.max_response_bytes
        timeout = httpx.Timeout(
            limits.response_timeout_seconds,
            connect=limits.connect_timeout_seconds,
        )
        self._client = httpx.Client(
            headers={"user-agent": user_agent},
            timeout=timeout,
            follow_redirects=False,
            transport=transport,
        )

    def __enter__(self) -> Self:
        """Enter the underlying HTTP client context."""
        self._client.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the underlying HTTP client context."""
        self._client.__exit__(exc_type, exc_value, traceback)

    def get_html(self, source_path: str) -> str:
        """Return one bounded HTML response from the approved source."""
        url = self._approved_url(source_path)
        for _redirect_count in range(MAX_REDIRECTS + 1):
            try:
                with self._client.stream("GET", url) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if location is None:
                            message = "redirect response is invalid"
                            raise FetchPermanentError(message)
                        url = self._approved_url(location, current_url=url)
                        continue
                    self._raise_for_status(response)
                    content_type = response.headers.get("content-type", "")
                    if content_type.split(";", maxsplit=1)[0].strip() != "text/html":
                        message = "response media type is not HTML"
                        raise FetchPermanentError(message)
                    content = self._read_bounded(response.iter_bytes())
                    return content.decode(
                        response.encoding or "utf-8", errors="replace"
                    )
            except httpx.TimeoutException:
                message = "source request timed out"
                raise FetchTemporaryError(message) from None
            except httpx.RequestError:
                message = "source request failed"
                raise FetchTemporaryError(message) from None
        message = "source response exceeded redirect limit"
        raise FetchPermanentError(message)

    def _approved_url(self, value: str, *, current_url: str | None = None) -> str:
        resolved = urljoin(current_url or self._base_url, value)
        parsed = urlsplit(resolved)
        host = parsed.hostname.lower() if parsed.hostname else ""
        port = parsed.port or 443
        if (
            parsed.scheme != "https"
            or host != self._approved_host
            or port != self._approved_port
        ):
            message = "request leaves the approved host boundary"
            raise FetchPermanentError(message)
        return resolved

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code == TOO_MANY_REQUESTS or (
            SERVER_ERROR_START <= response.status_code < SERVER_ERROR_END
        ):
            message = "source returned a temporary HTTP failure"
            raise FetchTemporaryError(message)
        if response.is_error:
            message = "source returned a permanent HTTP failure"
            raise FetchPermanentError(message)

    def _read_bounded(self, chunks: Iterator[bytes]) -> bytes:
        content = bytearray()
        for chunk in chunks:
            content.extend(chunk)
            if len(content) > self._max_response_bytes:
                message = "source response exceeds the configured size limit"
                raise FetchPermanentError(message)
        return bytes(content)
