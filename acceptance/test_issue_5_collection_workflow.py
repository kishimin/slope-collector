"""Acceptance coverage for complete, resumable historical collection."""

# Acceptance assertions intentionally describe the externally observable contract.
# ruff: noqa: INP001, S101

from typing import TYPE_CHECKING

import httpx
import pytest

from app.config import load_settings
from app.services.collection import CollectionMode, collect_all

if TYPE_CHECKING:
    from pathlib import Path

    from app.scraping.domain import CollectedRecord


class RecordingRepository:
    """Record stable identifiers as an operator-observable checkpoint."""

    def __init__(self) -> None:
        """Initialize an empty checkpoint."""
        self.identifiers: set[tuple[str, str, str]] = set()

    def persist(self, record: CollectedRecord) -> bool:
        """Return whether the record was absent from the checkpoint."""
        identifier = (
            record.source_key,
            record.entity_external_key,
            record.external_key,
        )
        if identifier in self.identifiers:
            return False
        self.identifiers.add(identifier)
        return True

    def existing_record_keys(
        self,
        _source_name: str,
        _entity_external_key: str,
        _record_external_keys: tuple[str, ...],
    ) -> frozenset[str]:
        """Return no preloaded keys for the acceptance checkpoint."""
        return frozenset()


@pytest.mark.medium
def test_backfill_reports_incomplete_when_history_never_reaches_natural_end(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Repeated historical content cannot be reported as a complete run."""
    values = {
        "DATABASE_URL": "mysql+pymysql://db/collector",
        "COLLECTOR_USER_AGENT": "slope-collector-test/1.0 contact@example.invalid",
        "COLLECTOR_MAX_PAGES": "5",
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

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/list":
            html = (
                '<article class="entry"><a class="detail" href="/detail/1">'
                "Item</a></article>"
                if request.url.params.get("page") == "0"
                else "<main></main>"
            )
        elif request.url.path == "/archive":
            page = request.url.params.get("page") or "0"
            next_page = "1" if page == "0" else "2"
            html = (
                '<article class="entry"><a class="detail" href="/detail/1">'
                'Item</a></article><a class="next" '
                f'href="/archive?entity=7&amp;page={next_page}">Next</a>'
            )
        else:
            html = (
                '<h1 class="title">Title</h1><time class="date">'
                '2026-09-18 12:30</time><span class="author">Author</span>'
                '<a class="author-link" href="/archive?entity=7">Author</a>'
                '<div class="body"><p>Body</p></div>'
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=html,
            request=request,
        )

    repository = RecordingRepository()
    first = collect_all(
        settings=load_settings(),
        source_keys=("source_a",),
        mode=CollectionMode.BACKFILL,
        repository=repository,
        transport=httpx.MockTransport(respond),
        sleep=lambda _delay: None,
    )
    resumed = collect_all(
        settings=load_settings(),
        source_keys=("source_a",),
        mode=CollectionMode.BACKFILL,
        repository=repository,
        transport=httpx.MockTransport(respond),
        sleep=lambda _delay: None,
    )

    assert first.failed_records > 0
    assert resumed.saved_records == 0
    assert len(repository.identifiers) == 1
