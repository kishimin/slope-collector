"""Collection pagination limit tests."""

from typing import TYPE_CHECKING

import httpx
import pytest

from app.config import load_settings
from app.services.collection import CollectionMode, collect_all

if TYPE_CHECKING:
    from pathlib import Path

    from app.scraping.domain import CollectedRecord


class RecordingRepository:
    """Minimal checkpoint double for pagination boundary coverage."""

    def persist(self, _record: CollectedRecord) -> bool:
        """Accept the valid record found before the page ceiling."""
        return True


@pytest.mark.medium
def test_page_ceiling_marks_collection_as_incomplete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A bounded backfill cannot claim success when another page remains."""
    values = {
        "DATABASE_URL": "mysql+pymysql://db/collector",
        "COLLECTOR_USER_AGENT": "slope-collector-test/1.0 contact@example.invalid",
        "COLLECTOR_MAX_PAGES": "1",
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
                'One</a></article><a class="next" href="/list?page=1">Next</a>'
            )
        else:
            html = (
                '<h1 class="title">Title</h1><time class="date">2026-09-18 12:30</time>'
                '<span class="author">Author</span><a class="author-link" '
                'href="/author?entity=7">Author</a><div class="body"><p>Body</p>'
                '<img src="https://cdn.example/1.jpg"></div>'
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
    )

    assert result.saved_records == 1
    assert result.failed_records == 1
