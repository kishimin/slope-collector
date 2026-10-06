"""Archived records retain their source identity and inactive status."""

from __future__ import annotations

import httpx
import pytest
from app.services.archive_collection import ArchiveConfig, collect_archive
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import Settings, SourceConfig
from app.models.collection import Base, Entity, Record
from app.repositories.collection import SqlAlchemyCollectionRepository
from app.services import archive_collection
from tests.medium.test_collection_repository import collected_record


@pytest.mark.medium
def test_archive_backfill_preserves_inactive_identity_and_skips_known_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All archive pages supplement one inactive source-owned member."""
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
        assert "script" not in record.body and "onclick" not in record.body
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
