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

    def __init__(self, existing_external_keys: set[str] | None = None) -> None:
        """Initialize the collected record list."""
        self.records: list[CollectedRecord] = []
        self.existing_external_keys = existing_external_keys or set()

    def persist(self, record: CollectedRecord) -> bool:
        """Record each unique historical item."""
        self.records.append(record)
        return True

    def exists(
        self,
        _source_key: str,
        _entity_external_key: str,
        record_external_key: str,
    ) -> bool:
        """Report whether a record was already recorded by this test double."""
        return record_external_key in self.existing_external_keys or any(
            record.external_key == record_external_key for record in self.records
        )


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
        elif request.url.path == "/author":
            html = (
                '<article class="entry"><a class="detail" href="/detail/1">'
                "One</a></article>"
                if request.url.params.get("page") is None
                else "<main></main>"
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

    expected_records = 3
    assert result.saved_records == expected_records
    assert result.failed_records == 0
    assert result.visited_pages == expected_records
    assert repository.records[0].entity_path == "/author?entity=7"


@pytest.mark.medium
def test_repeated_numbered_probe_is_natural_archive_end(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A clamped numbered probe does not make a complete run fail."""
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
            html = (
                "<main></main>"
                if request.url.params.get("page") == "2"
                else (
                    '<article class="entry"><a class="detail" '
                    'href="/detail/1">Item</a></article>'
                )
            )
        elif request.url.path == "/author":
            html = (
                '<article class="entry"><a class="detail" '
                'href="/detail/1">Item</a></article>'
            )
        else:
            html = (
                '<h1 class="title">Title</h1><time class="date">2026-09-18 12:30</time>'
                '<span class="author">Author</span><a class="author-link" '
                'href="/author?entity=7">Author</a><div class="body"><p>Body</p></div>'
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
        mode=CollectionMode.BACKFILL,
        repository=RecordingRepository(),
        transport=httpx.MockTransport(respond),
    )

    assert result.failed_records == 0


@pytest.mark.medium
def test_collection_traverses_discovered_member_archive(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Backfill follows each member archive discovered in a detail page."""
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
    expected_page_count = 4

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/list":
            page = request.url.params.get("page")
            record_id = "1" if page == "0" else "2" if page == "1" else None
            html = (
                "<main></main>"
                if record_id is None
                else (
                    f'<article class="entry"><a class="detail" '
                    f'href="/detail/{record_id}">Item</a></article>'
                )
            )
        elif request.url.path == "/author":
            page = request.url.params.get("page") or "0"
            record_id = "1" if page == "0" else "3" if page == "1" else None
            html = (
                "<main></main>"
                if record_id is None
                else (
                    f'<article class="entry"><a class="detail" '
                    f'href="/detail/{record_id}">Item</a></article>'
                )
            )
        else:
            html = (
                '<h1 class="title">Title</h1><time class="date">'
                '2026-09-18 12:30</time><span class="author">Author</span>'
                '<a class="author-link" href="/author?entity=7">Author</a>'
                '<div class="body"><p>Body</p><img src="https://cdn.example/1.jpg"></div>'
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

    assert result.failed_records == 0
    assert result.visited_pages == expected_page_count
    assert len(repository.records) == expected_page_count
    assert any(record.source_path == "/detail/3" for record in repository.records)


@pytest.mark.medium
def test_collection_filters_to_requested_source_entity_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A targeted backfill persists only the requested member's history."""
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
    detail_requests: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/list":
            page = request.url.params.get("page")
            assert request.url.params.get("entity") == "40"
            html = (
                '<article class="entry"><a class="detail" href="/detail/1">'
                "Target</a></article>"
                if page == "0"
                else (
                    '<article class="entry"><a class="detail" href="/detail/3">'
                    "Target history</a></article>"
                    if page == "1"
                    else "<main></main>"
                )
            )
        elif request.url.path == "/author":
            page = request.url.params.get("page") or "0"
            html = (
                '<article class="entry"><a class="detail" href="/detail/3">'
                "Target history</a></article>"
                if page == "0"
                else "<main></main>"
            )
        else:
            record_id = request.url.path.rsplit("/", maxsplit=1)[-1]
            detail_requests.append(record_id)
            entity_key = "40" if record_id in {"1", "3"} else "41"
            html = (
                f'<h1 class="title">Title {record_id}</h1><time class="date">'
                '2026-09-18 12:30</time><span class="author">Author</span>'
                f'<a class="author-link" href="/author?entity={entity_key}">'
                'Author</a><div class="body"><p>Body</p></div>'
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=html,
            request=request,
        )

    repository = RecordingRepository(existing_external_keys={"1"})
    result = collect_all(
        settings=load_settings(),
        source_keys=("source_a",),
        source_entity_key="40",
        mode=CollectionMode.BACKFILL,
        repository=repository,
        transport=httpx.MockTransport(respond),
    )

    assert result.failed_records == 0
    expected_saved_records = 1
    assert result.saved_records == expected_saved_records
    assert result.skipped_records == 1
    assert detail_requests == ["3"]
    assert {record.entity_external_key for record in repository.records} == {"40"}


@pytest.mark.medium
def test_collection_reports_first_entity_archive_parse_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A malformed first archive page makes the backfill outcome fail."""
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
            html = (
                '<article class="entry"><a class="detail" href="/detail/1">'
                "Item</a></article>"
                if request.url.params.get("page") == "0"
                else "<main></main>"
            )
        elif request.url.path == "/author":
            html = "<main></main>"
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
        mode=CollectionMode.BACKFILL,
        repository=RecordingRepository(),
        transport=httpx.MockTransport(respond),
    )

    assert result.saved_records == 1
    assert result.failed_records == 1


@pytest.mark.medium
def test_collection_reports_explicit_entity_archive_parse_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A malformed explicitly linked archive page makes the backfill fail."""
    values = {
        "DATABASE_URL": "mysql+pymysql://db/collector",
        "COLLECTOR_USER_AGENT": "slope-collector-test/1.0 contact@example.invalid",
        "COLLECTOR_MAX_PAGES": "4",
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
        elif request.url.path == "/author":
            html = (
                '<article class="entry"><a class="detail" href="/detail/2">'
                'Item</a></article><a class="next" '
                'href="/author?entity=7&amp;page=1">Next</a>'
                if request.url.params.get("page") is None
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
        mode=CollectionMode.BACKFILL,
        repository=RecordingRepository(),
        transport=httpx.MockTransport(respond),
    )

    expected_saved_records = 2
    assert result.saved_records == expected_saved_records
    assert result.failed_records == 1
