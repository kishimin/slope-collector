"""Acceptance coverage for full, resumable collection."""

from typing import TYPE_CHECKING

import httpx
import pytest

from app.config import load_settings
from app.services.collection import CollectionMode, collect_all

if TYPE_CHECKING:
    from pathlib import Path

    from app.scraping.domain import CollectedRecord


class MemoryRepository:
    """Observable persistence double for the operator collection story."""

    def __init__(self) -> None:
        """Start with no persisted collection checkpoints."""
        self.records: dict[tuple[str, str, str], CollectedRecord] = {}

    def persist(self, record: CollectedRecord) -> bool:
        """Store one record once and report whether it was new."""
        key = (record.source_key, record.entity_external_key, record.external_key)
        if key in self.records:
            return False
        self.records[key] = record
        return True


@pytest.mark.medium
def test_operator_can_backfill_every_page_and_resume_without_duplicates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Manual collection persists all pages and uses saved records as a checkpoint."""
    environment = {
        "DATABASE_URL": "mysql+pymysql://db/collector",
        "COLLECTOR_USER_AGENT": "slope-collector-test/1.0 contact@example.invalid",
        "COLLECTOR_MAX_PAGES": "10",
        "SOURCE_A_BASE_URL": "https://source.example",
        "SOURCE_A_LIST_PATH": "/list?page={page}",
        "SOURCE_A_DETAIL_PATH": "/detail/{record_id}",
        "SOURCE_A_ALLOWED_CDN_HOSTS": "cdn.example",
        "SOURCE_A_LIST_ITEM_SELECTOR": ".entry",
        "SOURCE_A_DETAIL_LINK_SELECTOR": ".detail-link",
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
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(tmp_path)

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/list" and request.url.params.get("page") == "0":
            html = (
                '<article class="entry"><a class="detail-link" href="/detail/1">'
                'One</a></article><a class="next" href="/list?page=1">Next</a>'
            )
        elif request.url.path == "/list":
            html = (
                '<article class="entry"><a class="detail-link" href="/detail/2">'
                "Two</a></article>"
            )
        else:
            record_id = request.url.path.rsplit("/", maxsplit=1)[-1]
            html = (
                f'<article><h1 class="title">Title {record_id}</h1>'
                '<time class="date">2026-09-18 12:30</time>'
                '<span class="author">Author</span>'
                '<a class="author-link" href="/author?entity=7">Author</a>'
                f'<div class="body"><p>Body {record_id}</p>'
                f'<img src="https://cdn.example/{record_id}.jpg" '
                f'alt="Image {record_id}"></div></article>'
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=html,
            request=request,
        )

    repository = MemoryRepository()
    transport = httpx.MockTransport(respond)

    first = collect_all(
        settings=load_settings(),
        source_keys=("source_a",),
        mode=CollectionMode.BACKFILL,
        repository=repository,
        transport=transport,
    )
    second = collect_all(
        settings=load_settings(),
        source_keys=("source_a",),
        mode=CollectionMode.BACKFILL,
        repository=repository,
        transport=transport,
    )

    expected_records = 2
    assert first.saved_records == expected_records
    assert first.skipped_records == 0
    assert second.saved_records == 0
    assert second.skipped_records == expected_records
    assert len(repository.records) == expected_records
    assert all(record.assets for record in repository.records.values())
