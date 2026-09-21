"""Acceptance coverage for retries and sanitized failure summaries."""

# Acceptance assertions intentionally describe the externally observable contract.
# ruff: noqa: INP001, S101

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Self, cast

import pytest

from app.scraping.http_client import FetchTemporaryError
from app.services.collection import (
    CollectionFailure,
    CollectionResult,
    _retry,
)
from app.services.notifications import notify_failures

if TYPE_CHECKING:
    from email.message import EmailMessage

    from app.config import Settings


@pytest.mark.small
def test_retry_uses_exponential_backoff_and_returns_after_transient_failure() -> None:
    """A transient operation is retried with increasing bounded delays."""
    attempts = 0
    delays: list[float] = []
    expected_attempts = 3

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < expected_attempts:
            message = "temporary"
            raise FetchTemporaryError(message)
        return "ok"

    settings = cast("Settings", SimpleNamespace(collector_retry_backoff_seconds=2.0))
    result = _retry(operation, settings=settings, sleep=delays.append)

    assert result == "ok"
    assert attempts == expected_attempts
    assert delays == [2.0, 4.0]


@pytest.mark.small
def test_failure_summary_contains_context_without_response_body() -> None:
    """One notification includes sanitized stage and exception context."""
    sent: list[EmailMessage] = []

    class FakeSmtp:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *arguments: object) -> None:
            return None

        def starttls(self) -> None:
            return None

        def login(self, _username: str, _password: str) -> None:
            return None

        def send_message(self, message: object) -> None:
            sent.append(cast("EmailMessage", message))

    settings = cast(
        "Settings",
        SimpleNamespace(
            mail_host="mail.example",
            mail_port=587,
            mail_username=SimpleNamespace(get_secret_value=lambda: "operator"),
            mail_password=SimpleNamespace(get_secret_value=lambda: "secret"),
            mail_from="from@example",
            mail_to="to@example",
        ),
    )
    failure = CollectionFailure(
        occurred_at=datetime(2026, 9, 21, 1, 2, tzinfo=UTC),
        stage="record",
        context="/records/example",
        exception_type="FetchTemporaryError",
        message="source request failed",
    )

    notify_failures(
        settings,
        CollectionResult(failed_records=1, failures=(failure,)),
        smtp_factory=lambda *_args, **_kwargs: FakeSmtp(),
    )

    message = sent[0]
    content = message.get_content()
    assert "stage=record" in content
    assert "context=/records/example" in content
    assert "source request failed" in content
