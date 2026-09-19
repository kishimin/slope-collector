"""Sequential historical page collection tests."""

from typing import TYPE_CHECKING

import httpx
import pytest

from app.config import load_settings
from app.services.collection import CollectionMode, collect_all

if TYPE_CHECKING:
    from pathlib import Path

    from app.scraping.domain import CollectedRecord


class RecordingRepository:
    """Minimal persistence double for historical page traversal."""

    def __init__(self) -> None:
        self.records: list[CollectedRecord] = []

    def persist(self, record: CollectedRecord) -> bool:
        """Record each unique historical item."""
        self.records.append(record)
        return True


@pytest.mark.medium
def test_collection_uses_numbered_pages_until_empty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A cycling next link cannot truncate numbered historical pages."""
    values = {
        "DATABASE_URL": "mysql+pymysql://db/collector",
        "COLLECTOR_USER_AGENT": "slope-collector-test/1.0 contact@example.invalid",
        "COLLECTOR_MAX_PAGES": "3",
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
            page = request.url.params.get("page")
            if page == "2":
                html = "<main></main>"
            else:
                record_id = "1" if page == "0" else "2"
                html = (
                    f'<article class="entry"><a class="detail" '
                    f'href="/detail/{record_id}">One</a></article>'
                    '<a class="next" href="/list?page=0">Next</a>'
                )
        else:
            html = (
                '<h1 class="title">Title</h1><time class="date">'
                '2026-09-18 12:30</time><span class="author">Author</span>'
                '<a class="author-link" href="/author?entity=7">Author</a>'
                '<div class="body"><p>Body</p><img '
                'src="https://cdn.example/1.jpg"></div>'
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=html,
            request=request,
        )

    repository = RecordingRepository()
    result = collect_all(
        settings=load_settings(),
        source_keys=("source_a",),
        mode=CollectionMode.BACKFILL,
        repository=repository,
        transport=httpx.MockTransport(respond),
    )

    assert result.saved_records == 2
    assert result.failed_records == 0
    assert result.visited_pages == 2
