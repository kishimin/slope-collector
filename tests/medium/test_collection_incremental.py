"""Incremental collection checkpoint tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from app.config import load_settings
from app.services.collection import CollectionMode, collect_all

if TYPE_CHECKING:
    from pathlib import Path

    from app.scraping.domain import CollectedRecord


class CheckpointRepository:
    """Store stable record keys to model a persisted collection checkpoint."""

    def __init__(self) -> None:
        """Initialize an empty checkpoint."""
        self.keys: set[str] = set()

    def persist(self, record: CollectedRecord) -> bool:
        """Return whether the mocked record was absent from the checkpoint."""
        external_key = record.external_key
        if external_key in self.keys:
            return False
        self.keys.add(external_key)
        return True


@pytest.mark.medium
def test_daily_collection_stops_at_the_first_persisted_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An incremental run does not request older pages after its checkpoint."""
    values = {
        "DATABASE_URL": "mysql+pymysql://db/collector",
        "COLLECTOR_USER_AGENT": "slope-collector-test/1.0 contact@example.invalid",
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

    requested_paths: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/list":
            page = request.url.params.get("page")
            html = (
                '<article class="entry"><a class="detail" '
                'href="/detail/1">Item</a></article>'
                if page == "0"
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

    repository = CheckpointRepository()
    first = collect_all(
        settings=load_settings(),
        source_keys=("source_a",),
        mode=CollectionMode.DAILY,
        repository=repository,
        transport=httpx.MockTransport(respond),
        sleep=lambda _delay: None,
    )
    requested_paths.clear()
    second = collect_all(
        settings=load_settings(),
        source_keys=("source_a",),
        mode=CollectionMode.DAILY,
        repository=repository,
        transport=httpx.MockTransport(respond),
        sleep=lambda _delay: None,
    )

    assert first.saved_records == 1
    assert second.saved_records == 0
    assert second.skipped_records == 1
    assert requested_paths == ["/list", "/detail/1"]
