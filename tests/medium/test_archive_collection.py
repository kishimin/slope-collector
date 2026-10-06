"""Archived records retain their source identity and inactive status."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest
from pydantic import JsonValue, ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import Settings, SourceConfig
from app.models.collection import Base, Entity, Record
from app.repositories.collection import SqlAlchemyCollectionRepository
from app.services import archive_collection
from app.services.archive_collection import ArchiveConfig, collect_archive
from tests.medium.test_collection_repository import collected_record

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def archive_context(monkeypatch: pytest.MonkeyPatch) -> tuple[Settings, ArchiveConfig]:
    """Provide private source and archive contracts using anonymous targets."""
    source = SourceConfig.model_validate(
        {
            "name": "source_a",
            "base_url": "https://source.example",
            "list_path": "/list",
            "detail_path": "/detail/{record_id}",
            "allowed_cdn_hosts": ["cdn.example"],
            "selectors": dict.fromkeys(
                (
                    "list_item",
                    "detail_link",
                    "title",
                    "body",
                    "published_at",
                    "author",
                    "entity_link",
                    "asset",
                    "next_page",
                ),
                ".unused",
            ),
            "record_id_pattern": r"/detail/(?P<record_id>\d+)",
            "entity_id_query_param": "entity",
            "published_at_format": "%Y-%m-%d %H:%M",
        }
    )
    monkeypatch.setattr(archive_collection, "load_source_config", lambda *_: source)
    settings = Settings.model_validate(
        {
            "database_url": "mysql+pymysql://db/collector",
            "collector_user_agent": "collector-test contact@example.invalid",
        }
    )
    config = ArchiveConfig.model_validate(
        {
            "base_url": "https://archive.example",
            "list_path": "/archive?member={entity_key}&page={page}",
            "detail_path": "/article/{record_id}",
            "entity_key": "old-7",
            "entity_name": "Example author",
            "fields": {
                "records": "items",
                "pages": "pages",
                "record_id": "id",
                "original_url": "url",
                "author": "author",
                "title": "title",
                "body": "body",
                "published_at": "date",
            },
        }
    )
    return settings, config


@pytest.mark.medium
@pytest.mark.parametrize("stored_key", ["7", "legacy:1"])
def test_archive_backfill_preserves_inactive_identity_and_skips_known_details(
    archive_context: tuple[Settings, ArchiveConfig],
    stored_key: str,
) -> None:
    """All archive pages supplement one inactive source-owned member."""
    settings, config = archive_context
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    repository = SqlAlchemyCollectionRepository(sessions)
    repository.persist(collected_record())
    with sessions.begin() as session:
        entity = session.scalar(select(Entity))
        assert entity is not None
        original_id = entity.id
        entity.is_active = False
        entity.external_key = stored_key

    requested: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.path == "/archive":
            key = 42 if request.url.params["page"] == "0" else 43
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": key,
                            "url": f"https://source.example/detail/{key}",
                            "author": "Example author",
                        }
                    ],
                    "pages": 2,
                },
            )
        return httpx.Response(
            200,
            json={
                "title": "Recovered",
                "author": "Example author",
                "body": '<p onclick="bad()">Recovered</p><script>bad()</script>',
                "date": "2026-09-18T03:30:00Z",
            },
        )

    result = collect_archive(
        settings=settings,
        source_key="source_a",
        source_entity_key="7",
        config=config,
        repository=repository,
        transport=httpx.MockTransport(respond),
        sleep=lambda _: None,
    )
    assert (
        result.saved_records,
        result.skipped_records,
        result.failed_records,
        result.visited_pages,
    ) == (1, 1, 0, 2)
    assert not any("/article/42" in url for url in requested)
    with sessions() as session:
        entity = session.scalar(select(Entity))
        assert entity is not None
        assert (entity.id, entity.external_key, entity.is_active) == (
            original_id,
            "7",
            False,
        )
        record = session.scalar(select(Record).where(Record.external_key == "43"))
        assert record is not None
        assert record.source_url == "/detail/43"
        assert "Recovered" in record.body
        assert "script" not in record.body
        assert "onclick" not in record.body
    engine.dispose()


@pytest.mark.medium
def test_archive_persistence_creates_an_inactive_member() -> None:
    """Previously absent archived members never enter active daily collection."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    repository = SqlAlchemyCollectionRepository(sessions)
    assert repository.persist_archive(collected_record()) is True
    assert repository.is_entity_active("source_a", "7") is False
    assert repository.persist_archive(collected_record()) is False
    engine.dispose()


@pytest.mark.medium
def test_archive_exclusion_preserves_records_without_any_source_requests(
    archive_context: tuple[Settings, ArchiveConfig],
) -> None:
    """A privately excluded member keeps its existing history untouched."""
    settings, original = archive_context
    config = ArchiveConfig.model_validate(
        {
            **original.model_dump(),
            "excluded_source_entity_keys": ["7"],
        }
    )
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    repository = SqlAlchemyCollectionRepository(sessions)
    repository.persist_archive(collected_record())
    with sessions() as session:
        before = session.scalar(select(Record))
        assert before is not None
        checkpoint = (before.id, before.title, before.body, before.source_url)
    requests: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(500)

    result = collect_archive(
        settings=settings,
        source_key="source_a",
        source_entity_key="7",
        config=config,
        repository=repository,
        transport=httpx.MockTransport(respond),
        sleep=lambda _: None,
    )
    assert requests == []
    assert result.visited_pages == 0
    assert result.saved_records == 0
    assert result.failed_records == 0
    with sessions() as session:
        records = session.scalars(select(Record)).all()
        assert [(r.id, r.title, r.body, r.source_url) for r in records] == [checkpoint]
        entity = session.scalar(select(Entity))
        assert entity is not None
        assert entity.is_active is False
    engine.dispose()


@pytest.mark.medium
@pytest.mark.parametrize(
    "problem",
    [
        "list-author",
        "detail-author",
        "original-url",
        "timezone",
        "text",
        "key",
        "page-count",
        "empty-list",
        "list-object",
        "detail-object",
        "missing-field",
        "malformed-json",
        "page-change",
        "page-limit",
        "repeated-page",
    ],
)
def test_archive_reports_invalid_contracts_without_persisting_wrong_records(
    archive_context: tuple[Settings, ArchiveConfig],
    problem: str,
) -> None:
    """Bad identity, incomplete pagination and malformed responses fail visibly."""
    settings, config = archive_context
    if problem == "page-limit":
        settings = settings.model_copy(update={"collector_max_pages": 1})
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    repository = SqlAlchemyCollectionRepository(sessions)

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/archive":
            return invalid_list_response(problem, request)
        return invalid_detail_response(problem)

    result = collect_archive(
        settings=settings,
        source_key="source_a",
        source_entity_key="7",
        config=config,
        repository=repository,
        transport=httpx.MockTransport(respond),
        sleep=lambda _: None,
    )
    assert result.failed_records == 1
    expected_saved = (
        1 if problem in {"page-change", "page-limit", "repeated-page"} else 0
    )
    assert result.saved_records == expected_saved
    engine.dispose()


@pytest.mark.medium
def test_archive_retries_temporary_failure_and_respects_request_pacing(
    archive_context: tuple[Settings, ArchiveConfig],
) -> None:
    """A temporary error retries serially and every request remains paced."""
    settings, config = archive_context
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    pauses: list[float] = []
    requests = 0

    def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        if requests == 1:
            return httpx.Response(429)
        return httpx.Response(200, json={"items": [], "pages": 0})

    result = collect_archive(
        settings=settings,
        source_key="source_a",
        source_entity_key="7",
        config=config,
        repository=SqlAlchemyCollectionRepository(sessionmaker(engine)),
        transport=httpx.MockTransport(respond),
        sleep=pauses.append,
    )
    expected_requests = 2
    assert requests == expected_requests
    assert result.failed_records == 0
    expected_pauses = 3
    assert len(pauses) == expected_pauses
    assert pauses[0] >= settings.collector_request_interval_seconds
    assert pauses[-1] >= settings.collector_request_interval_seconds
    engine.dispose()


@pytest.mark.medium
def test_archive_config_hides_private_errors(tmp_path: Path) -> None:
    """Invalid private files fail without disclosing their contents."""
    path = tmp_path / "private.json"
    path.write_text('{"private": "do-not-disclose"}', encoding="utf-8")
    with pytest.raises(ValueError, match=r"^archive configuration file is invalid$"):
        archive_collection.load_archive_config(str(path))


@pytest.mark.medium
@pytest.mark.parametrize(
    "update",
    [
        {"base_url": "http://archive.example"},
        {"list_path": "//other.example/list"},
    ],
)
def test_archive_rejects_unapproved_transport_configuration(
    archive_context: tuple[Settings, ArchiveConfig],
    update: dict[str, str],
) -> None:
    """Private configuration cannot relax the HTTPS host boundary."""
    _, config = archive_context
    with pytest.raises(ValidationError):
        ArchiveConfig.model_validate({**config.model_dump(), **update})


def invalid_list_response(problem: str, request: httpx.Request) -> httpx.Response:
    """Return one deliberately invalid list contract."""
    item: dict[str, JsonValue] = {
        "id": 42,
        "url": "https://source.example/detail/42",
        "author": "Example author",
    }
    payload: dict[str, JsonValue] = {"items": [item], "pages": 1}
    if problem == "list-author":
        item["author"] = "Other author"
    elif problem == "original-url":
        item["url"] = "https://source.example/detail/43"
    elif problem == "key":
        item["id"] = True
    elif problem == "page-count":
        payload["pages"] = True
    elif problem == "empty-list":
        payload["items"] = []
    elif problem == "list-object":
        return httpx.Response(200, json=[])
    elif problem == "page-change":
        payload["pages"] = 2 if request.url.params["page"] == "0" else 3
    elif problem in {"page-limit", "repeated-page"}:
        payload["pages"] = 2
    elif problem == "malformed-json":
        return httpx.Response(
            200, headers={"content-type": "application/json"}, text="{"
        )
    return httpx.Response(200, json=payload)


def invalid_detail_response(problem: str) -> httpx.Response:
    """Return one deliberately invalid detail contract."""
    detail: dict[str, JsonValue] = {
        "title": "Recovered",
        "author": "Example author",
        "body": "<p>Recovered</p>",
        "date": "2026-09-18T03:30:00Z",
    }
    if problem == "detail-author":
        detail["author"] = "Other author"
    elif problem == "timezone":
        detail["date"] = "2026-09-18T03:30:00"
    elif problem == "text":
        detail["title"] = 3
    elif problem == "detail-object":
        return httpx.Response(200, json=[])
    elif problem == "missing-field":
        del detail["body"]
    return httpx.Response(200, json=detail)
