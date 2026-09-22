"""Collector retry and failure notification integration tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

import httpx
import pytest

from app.config import load_settings
from app.services.collection import CollectionMode, collect_all
from app.services.notifications import notify_failures

if TYPE_CHECKING:
    from email.message import EmailMessage
    from pathlib import Path

    from app.scraping.domain import CollectedRecord


class RecordingRepository:
    """Accept records while exposing the collector's observable result."""

    def existing_record_keys(
        self,
        _source_key: str,
        _entity_external_key: str,
        _record_external_keys: tuple[str, ...],
    ) -> frozenset[str]:
        """Expose an empty persisted checkpoint for this scenario."""
        return frozenset()

    def __init__(self) -> None:
        """Initialize an empty record list."""
        self.records: list[CollectedRecord] = []

    def persist(self, record: CollectedRecord) -> bool:
        """Store each record once for this integration scenario."""
        self.records.append(record)
        return True


def configure_source(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Configure an anonymous source contract for mocked HTTP calls."""
    values = {
        "DATABASE_URL": "mysql+pymysql://db/collector",
        "COLLECTOR_USER_AGENT": "slope-collector-test/1.0 contact@example.invalid",
        "COLLECTOR_RETRY_BACKOFF_SECONDS": "2",
        "COLLECTOR_REQUEST_INTERVAL_SECONDS": "0",
        "COLLECTOR_REQUEST_JITTER_SECONDS": "0",
        "COLLECTOR_MAX_PAGES": "2",
        "SOURCE_A_BASE_URL": "https://source.example",
        "SOURCE_A_LIST_PATH": "/list?page={page}",
        "SOURCE_A_DETAIL_PATH": "/detail/{record_id}",
        "SOURCE_A_ALLOWED_CDN_HOSTS": "cdn.example",
        "SOURCE_A_LIST_ITEM_SELECTOR": ".entry",
        "SOURCE_A_DETAIL_LINK_SELECTOR": ".detail",
        "SOURCE_A_TITLE_SELECTOR": ".title",
        "SOURCE_A_BODY_SELECTOR": ".body",
        "SOURCE_A_DATE_SELECTOR": ".date",
        "SOURCE_A_AUTHOR_SELECTOR": ".author",
        "SOURCE_A_ENTITY_LINK_SELECTOR": ".author-link",
        "SOURCE_A_ASSET_SELECTOR": ".body img",
        "SOURCE_A_NEXT_PAGE_SELECTOR": ".next",
        "SOURCE_A_RECORD_ID_PATTERN": r"/detail/(?P<record_id>\d+)",
        "SOURCE_A_ENTITY_ID_QUERY_PARAM": "entity",
        "SOURCE_A_PUBLISHED_AT_FORMAT": "%Y-%m-%d %H:%M",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(tmp_path)


@pytest.mark.medium
def test_collector_retries_transient_http_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A temporary list failure is retried before the record is persisted."""
    configure_source(monkeypatch, tmp_path)
    list_attempts = 0
    delays: list[float] = []
    expected_attempts = 3

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal list_attempts
        if request.url.path == "/list":
            list_attempts += 1
            if list_attempts < expected_attempts:
                return httpx.Response(503, request=request)
            html = (
                '<article class="entry"><a class="detail" '
                'href="/detail/1">Item</a></article>'
                if request.url.params.get("page") == "0"
                else "<main></main>"
            )
        else:
            html = (
                '<h1 class="title">Title</h1><time class="date">'
                '2026-09-18 12:30</time><span class="author">Author</span>'
                '<a class="author-link" href="/author?entity=7">Author</a>'
                '<div class="body"><p>Body</p></div>'
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=html,
            request=request,
        )

    result = collect_all(
        settings=load_settings(),
        source_keys=("source_a",),
        mode=CollectionMode.DAILY,
        repository=RecordingRepository(),
        transport=httpx.MockTransport(respond),
        sleep=delays.append,
    )

    assert result.saved_records == 1
    assert result.failed_records == 0
    assert list_attempts == expected_attempts + 1
    assert [delay for delay in delays if delay > 0] == [2, 4]


@pytest.mark.medium
def test_collector_failure_is_reported_in_one_sanitized_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An unresolved record failure becomes one operator summary."""
    configure_source(monkeypatch, tmp_path)
    monkeypatch.setenv("MAIL_HOST", "mail.example")
    monkeypatch.setenv("MAIL_FROM", "from@example.invalid")
    monkeypatch.setenv("MAIL_TO", "to@example.invalid")
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
            sent.append(message)  # type: ignore[arg-type]

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/list":
            html = (
                '<article class="entry"><a class="detail" '
                'href="/detail/1">Item</a></article>'
                if request.url.params.get("page") == "0"
                else "<main></main>"
            )
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text=html,
                request=request,
            )
        return httpx.Response(400, request=request)

    result = collect_all(
        settings=load_settings(),
        source_keys=("source_a",),
        mode=CollectionMode.DAILY,
        repository=RecordingRepository(),
        transport=httpx.MockTransport(respond),
        sleep=lambda _delay: None,
    )
    notify_failures(
        load_settings(), result, smtp_factory=lambda *_args, **_kwargs: FakeSmtp()
    )

    assert result.saved_records == 0
    assert result.failed_records == 1
    assert len(sent) == 1
    content = sent[0].get_content()
    assert "stage=record" in content
    assert "exception=FetchPermanentError" in content
    assert "response body" not in content
