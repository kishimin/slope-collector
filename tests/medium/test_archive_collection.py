"""Archived records retain their source identity and inactive status."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
import pytest
from pydantic import JsonValue, SecretStr, ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import Settings, SourceConfig, SourceSelectors
from app.models.collection import Asset, Base, Entity, Record, Source
from app.models.control import Target
from app.recovery import run_recovery_checks
from app.repositories.collection import SqlAlchemyCollectionRepository
from app.repositories.control import SqlAlchemyControlRepository
from app.services import archive_collection
from app.services.archive_collection import ArchiveConfig, collect_archive
from tests.medium.test_collection_repository import collected_record

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.orm import Session


@pytest.fixture
def source_name() -> str:
    """Use the stable source name unless a test selects a renamed source."""
    return "source_a"


@pytest.fixture
def archive_context(
    monkeypatch: pytest.MonkeyPatch, source_name: str
) -> tuple[Settings, ArchiveConfig]:
    """Provide private source and archive contracts using anonymous targets."""
    source = SourceConfig.model_validate(
        {
            "name": source_name,
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
@pytest.mark.parametrize("pause_at", ["before", "list", "detail", "retry", "wait"])
def test_archive_pause_preserves_completed_records(
    archive_context: tuple[Settings, ArchiveConfig],
    control_sessions: sessionmaker[Session],
    pause_at: str,
) -> None:
    """Archive maintenance suppresses subsequent requests without rolling back saves."""
    settings, config = archive_context
    controls = SqlAlchemyControlRepository(control_sessions)
    repository = SqlAlchemyCollectionRepository(control_sessions)
    target = Target("source_a", "archive")

    def pause() -> None:
        controls.pause(
            target,
            resume_mode="manual",
            interval=60,
            reason=None,
            now=datetime.now(UTC),
        )

    if pause_at == "before":
        pause()
    paths: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/archive":
            if pause_at in {"list", "retry"}:
                pause()
            if pause_at == "retry":
                return httpx.Response(503)
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": key,
                            "url": f"https://source.example/detail/{key}",
                            "author": "Example author",
                        }
                        for key in (42, 43)
                    ],
                    "pages": 1,
                },
            )
        if pause_at == "detail":
            pause()
        return httpx.Response(
            200,
            json={
                "title": "Recovered",
                "author": "Example author",
                "body": "<p>Recovered</p>",
                "date": "2026-09-18T03:30:00Z",
            },
        )

    def sleep(_delay: float) -> None:
        if pause_at == "wait":
            pause()

    result = collect_archive(
        settings=settings,
        source_key="source_a",
        source_entity_key="7",
        config=config,
        repository=repository,
        controls=controls,
        transport=httpx.MockTransport(respond),
        sleep=sleep,
    )
    expected = {
        "before": [],
        "list": ["/archive"],
        "detail": ["/archive", "/article/42"],
        "retry": ["/archive"],
        "wait": [],
    }
    assert paths == expected[pause_at]
    assert result.saved_records == (1 if pause_at == "detail" else 0)
    assert result.failed_records == 0
    assert result.paused_sites == (target.key,)


@pytest.mark.medium
@pytest.mark.parametrize(
    "problem", [None, "list", "detail", "missing-field", "empty-list"]
)
@pytest.mark.parametrize("detail_format", ["json", "html"])
def test_archive_recovery_uses_private_contract_without_saving(
    archive_context: tuple[Settings, ArchiveConfig],
    control_sessions: sessionmaker[Session],
    tmp_path: Path,
    problem: str | None,
    detail_format: str,
) -> None:
    """Only a valid archive list and first detail release a due automatic pause."""
    settings, config = archive_context
    if detail_format == "html":
        config = config.model_copy(
            update={
                "detail_format": "html",
                "original_selectors": SourceSelectors(
                    list_item=".entry",
                    detail_link=".detail",
                    title=".title",
                    body=".body",
                    published_at=".date",
                    author=".author",
                    entity_link=".author-link",
                    asset=".body img",
                    next_page=".next",
                ),
            }
        )
    contract = tmp_path / ".env.archive.json"
    contract.write_text(config.model_dump_json(), encoding="utf-8")
    manifest = tmp_path / ".env.recovery.json"
    manifest.write_text(
        '[{"source":"source_a","site":"archive","source_entity_key":"7",'
        '"archive_config_path":".env.archive.json"}]',
        encoding="utf-8",
    )
    settings = settings.model_copy(
        update={"collector_recovery_config_path": SecretStr(str(manifest))}
    )
    controls = SqlAlchemyControlRepository(control_sessions)
    target = Target("source_a", "archive")
    now = datetime(2026, 10, 24, tzinfo=UTC)
    controls.pause(target, resume_mode="automatic", interval=60, reason=None, now=now)
    paths: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        problem_responses = {
            "list": httpx.Response(200, text="Maintenance"),
            "empty-list": httpx.Response(200, json={"items": [], "pages": 0}),
        }
        if problem in problem_responses:
            return problem_responses[problem]
        if request.url.path == "/archive":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": 42,
                            "url": "https://source.example/detail/42",
                            "author": "Example author",
                        }
                    ],
                    "pages": 1,
                },
            )
        if detail_format == "html":
            html = (
                '<h1 class="title">Recovered</h1><time class="date">'
                '2026-09-18 12:30</time><span class="author">Example author</span>'
                '<a class="author-link" href="/author?entity=7">Example author</a>'
                '<div class="body"><p>Recovered</p></div>'
            )
            if problem in {"detail", "missing-field"}:
                html = "<h1>Maintenance</h1>"
            return httpx.Response(200, headers={"content-type": "text/html"}, text=html)
        if problem == "detail":
            return httpx.Response(200, json={"author": "Wrong author"})
        if problem == "missing-field":
            return httpx.Response(200, json={"author": "Example author"})
        return httpx.Response(
            200,
            json={
                "title": "Recovered",
                "author": "Example author",
                "body": "<p>Recovered</p>",
                "date": "2026-09-18T03:30:00Z",
            },
        )

    result = run_recovery_checks(
        settings=settings,
        repository=controls,
        now=lambda: now + timedelta(hours=1),
        transport=httpx.MockTransport(respond),
        sleep=lambda _: None,
    )
    detail_path = "/detail/42" if detail_format == "html" else "/article/42"
    assert paths == (
        ["/archive"] if problem in {"list", "empty-list"} else ["/archive", detail_path]
    )
    assert result.checked == 1
    assert result.resumed == (1 if problem is None else 0)
    state = controls.get(target)
    assert state.paused is (problem is not None)
    assert state.last_check_succeeded is (problem is None)
    assert state.last_checked_at == now + timedelta(hours=1)
    assert state.next_check_at == (
        now + timedelta(hours=2) if problem is not None else None
    )
    with control_sessions() as session:
        assert session.scalar(select(Record)) is None


@pytest.mark.medium
def test_empty_archive_recovery_does_not_block_later_due_site(
    archive_context: tuple[Settings, ArchiveConfig],
    control_sessions: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    """An empty archive records failure while a later healthy archive can resume."""
    settings, config = archive_context
    healthy = ArchiveConfig.model_validate(
        {**config.model_dump(), "base_url": "https://healthy-archive.example"}
    )
    (tmp_path / ".env.empty.json").write_text(
        config.model_dump_json(), encoding="utf-8"
    )
    (tmp_path / ".env.healthy.json").write_text(
        healthy.model_dump_json(), encoding="utf-8"
    )
    manifest = tmp_path / ".env.recovery.json"
    manifest.write_text(
        '[{"source":"source_a","site":"archive","source_entity_key":"7",'
        '"archive_config_path":".env.empty.json"},'
        '{"source":"source_b","site":"archive","source_entity_key":"7",'
        '"archive_config_path":".env.healthy.json"}]',
        encoding="utf-8",
    )
    settings = settings.model_copy(
        update={"collector_recovery_config_path": SecretStr(str(manifest))}
    )
    controls = SqlAlchemyControlRepository(control_sessions)
    empty = Target("source_a", "archive")
    available = Target("source_b", "archive")
    now = datetime(2026, 10, 24, tzinfo=UTC)
    for target in (empty, available):
        controls.pause(
            target, resume_mode="automatic", interval=60, reason=None, now=now
        )
    requested: list[tuple[str, str]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requested.append((request.url.host, request.url.path))
        if request.url.host == "archive.example":
            return httpx.Response(200, json={"items": [], "pages": 0})
        if request.url.path == "/archive":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": 42,
                            "url": "https://source.example/detail/42",
                            "author": "Example author",
                        }
                    ],
                    "pages": 1,
                },
            )
        return httpx.Response(
            200,
            json={
                "title": "Recovered",
                "author": "Example author",
                "body": "<p>Recovered</p>",
                "date": "2026-09-18T03:30:00Z",
            },
        )

    result = run_recovery_checks(
        settings=settings,
        repository=controls,
        now=lambda: now + timedelta(hours=1),
        sleep=lambda _: None,
        transport=httpx.MockTransport(respond),
    )
    assert (result.checked, result.failed, result.resumed) == (2, 1, 1)
    assert requested == [
        ("archive.example", "/archive"),
        ("healthy-archive.example", "/archive"),
        ("healthy-archive.example", "/article/42"),
    ]
    state = controls.get(empty)
    assert state.paused is True
    assert state.last_check_succeeded is False
    assert state.last_check_error == "recovery check failed"
    assert state.next_check_at == now + timedelta(hours=2)
    assert controls.get(available).paused is False
    with control_sessions() as session:
        assert session.scalar(select(Record)) is None


@pytest.mark.medium
@pytest.mark.parametrize("stored_key", ["7", "legacy:1"])
@pytest.mark.parametrize("source_name", ["source_a", "Renamed source"])
def test_archive_backfill_preserves_inactive_identity_and_skips_known_details(
    archive_context: tuple[Settings, ArchiveConfig],
    stored_key: str,
    source_name: str,
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
        assert session.scalar(select(Source.name)) == source_name
        record = session.scalar(select(Record).where(Record.external_key == "43"))
        assert record is not None
        assert record.source_url == "/detail/43"
        assert "Recovered" in record.body
        assert "script" not in record.body
        assert "onclick" not in record.body
    engine.dispose()


@pytest.mark.medium
@pytest.mark.parametrize("detail_format", ["json", "html"])
@pytest.mark.parametrize("legacy_port", ["", ":8080"])
@pytest.mark.parametrize(
    "mapping_case", ["exact", "none", "other-src", "other-host", "omit", "other-omit"]
)
def test_archive_exact_image_replacements_preserve_body_and_asset_contracts(
    archive_context: tuple[Settings, ArchiveConfig],
    detail_format: str,
    mapping_case: str,
    legacy_port: str,
) -> None:
    """Only explicitly approved img sources recover while links and text remain."""
    settings, original = archive_context
    old = (
        "cid:/legacy/image.jpg"
        if mapping_case in {"omit", "other-omit"} and not legacy_port
        else f"http://legacy.example{legacy_port}/old.jpg"
    )
    new = "https://cdn.example/recovered.jpg"
    replacement = {
        "exact": {old: new},
        "other-src": {old + "?other=1": new},
        "other-host": {old: "https://unapproved.example/recovered.jpg"},
    }.get(mapping_case, {})
    config = ArchiveConfig.model_validate(
        {
            **original.model_dump(),
            "detail_format": detail_format,
            "image_url_replacements": replacement,
            "omitted_image_urls": (
                [old if mapping_case == "omit" else "cid:/legacy/other.jpg"]
                if mapping_case in {"omit", "other-omit"}
                else []
            ),
            "original_selectors": {
                **dict.fromkeys(("list_item", "detail_link", "next_page"), ".unused"),
                "title": ".title",
                "body": ".body",
                "published_at": ".date",
                "author": ".author",
                "entity_link": ".entity",
                "asset": "img",
            },
        }
    )
    body = f'<p>{old}</p><a href="{old}">Link</a><img src="{old}" alt="Recovered">'
    if mapping_case in {"omit", "other-omit"}:
        body += '<img src="https://cdn.example/kept.jpg" alt="Kept">'
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    requests: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.path == "/archive":
            return httpx.Response(
                200,
                json={
                    "pages": 1,
                    "items": [
                        {
                            "id": 42,
                            "url": "https://source.example/detail/42",
                            "author": "Example author",
                        }
                    ],
                },
            )
        if detail_format == "json":
            return httpx.Response(
                200,
                json={
                    "title": "Recovered",
                    "body": body,
                    "author": "Example author",
                    "date": "2020-01-01T00:00:00Z",
                },
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text='<h1 class="title">Recovered</h1>'
            '<time class="date">2020-01-01 12:00</time>'
            '<span class="author">Example author</span>'
            '<a class="entity" href="/?entity=7">Example author</a>'
            f'<div class="body">{body}</div>',
        )

    result = collect_archive(
        settings=settings,
        source_key="source_a",
        source_entity_key="7",
        config=config,
        repository=SqlAlchemyCollectionRepository(sessions),
        transport=httpx.MockTransport(respond),
        sleep=lambda _: None,
    )
    if mapping_case not in {"exact", "omit"}:
        assert (result.saved_records, result.failed_records) == (0, 1)
        if mapping_case == "other-host":
            assert requests == []
        engine.dispose()
        return
    assert (result.saved_records, result.failed_records) == (1, 0)
    with sessions() as session:
        record = session.scalar(select(Record))
        assert record is not None
        assert f"<p>{old}</p>" in record.body
        expected = "/kept.jpg" if mapping_case == "omit" else "/recovered.jpg"
        assert f'src="{expected}"' in record.body
        if mapping_case == "omit":
            assert "Recovered" not in record.body
        assert f'href="{new}"' not in record.body
        assert session.scalar(select(Asset.source_url)) == expected
    engine.dispose()


@pytest.mark.medium
@pytest.mark.parametrize(
    "legacy_url",
    ["http://legacy.example:8080/old.jpg", "https://legacy.example:8443/old.jpg"],
)
@pytest.mark.parametrize("operation", ["replace", "omit"])
def test_archive_accepts_nonstandard_ports_only_in_unfetched_image_references(
    archive_context: tuple[Settings, ArchiveConfig], legacy_url: str, operation: str
) -> None:
    """Legacy sources are exact match strings rather than network destinations."""
    _, original = archive_context
    updates = (
        {"image_url_replacements": {legacy_url: "https://cdn.example/recovered.jpg"}}
        if operation == "replace"
        else {"omitted_image_urls": [legacy_url]}
    )
    config = ArchiveConfig.model_validate({**original.model_dump(), **updates})
    if operation == "replace":
        assert config.image_url_replacements == {
            legacy_url: "https://cdn.example/recovered.jpg"
        }
    else:
        assert config.omitted_image_urls == (legacy_url,)


@pytest.mark.medium
@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("cid:local", "https://cdn.example/recovered.jpg"),
        ("javascript:bad()", "https://cdn.example/recovered.jpg"),
        ("/old.jpg", "https://cdn.example/recovered.jpg"),
        ("http://legacy.example:invalid/old.jpg", "https://cdn.example/recovered.jpg"),
        ("http://legacy.example:65536/old.jpg", "https://cdn.example/recovered.jpg"),
        ("http://legacy.example/old.jpg", "http://cdn.example/recovered.jpg"),
        ("http://legacy.example/old.jpg", "https://user@cdn.example/recovered.jpg"),
        ("http://legacy.example/old.jpg", "https://cdn.example:444/recovered.jpg"),
        ("http://legacy.example/old.jpg", "https://cdn.example:invalid/recovered.jpg"),
    ],
)
def test_archive_rejects_unsafe_image_replacement_urls(
    archive_context: tuple[Settings, ArchiveConfig], old: str, new: str
) -> None:
    """Require network origins and credential-free HTTPS image destinations."""
    _, config = archive_context
    with pytest.raises(ValidationError):
        ArchiveConfig.model_validate(
            {**config.model_dump(), "image_url_replacements": {old: new}}
        )


@pytest.mark.medium
@pytest.mark.parametrize(
    "update",
    [
        {"omitted_image_urls": ["javascript:bad()"]},
        {"omitted_image_urls": ["cid:relative"]},
        {"omitted_image_urls": ["cid:/" + "x" * 4096]},
        {"omitted_image_urls": ["cid:/image"] * 101},
        {
            "omitted_image_urls": ["http://legacy.example/image.jpg"],
            "image_url_replacements": {
                "http://legacy.example/image.jpg": "https://cdn.example/image.jpg"
            },
        },
    ],
)
def test_archive_rejects_ambiguous_or_unbounded_image_omissions(
    archive_context: tuple[Settings, ArchiveConfig], update: dict[str, JsonValue]
) -> None:
    """Explicit omissions cannot conflict with replacements or relax URL bounds."""
    _, config = archive_context
    with pytest.raises(ValidationError):
        ArchiveConfig.model_validate({**config.model_dump(), **update})


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
@pytest.mark.parametrize("source_name", ["source_c"])
def test_third_source_archive_preserves_identity_and_restart_checkpoints(
    archive_context: tuple[Settings, ArchiveConfig], source_name: str
) -> None:
    """Preserve the archive persistence and restart contract for the optional source."""
    settings, config = archive_context
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    requests: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/archive":
            return httpx.Response(
                200,
                json={
                    "pages": 1,
                    "items": [
                        {
                            "id": 42,
                            "url": "https://source.example/detail/42",
                            "author": "Example author",
                        }
                    ],
                },
            )
        return invalid_detail_response("")

    for saved, skipped in ((1, 0), (0, 1)):
        result = collect_archive(
            settings=settings,
            source_key="source_c",
            source_entity_key="7",
            config=config,
            repository=SqlAlchemyCollectionRepository(sessions),
            transport=httpx.MockTransport(respond),
            sleep=lambda _: None,
        )
        assert (
            result.saved_records,
            result.skipped_records,
            result.failed_records,
        ) == (saved, skipped, 0)
    assert requests == ["/archive", "/article/42", "/archive"]
    with sessions() as session:
        sources = session.scalars(select(Source)).all()
        entities = session.scalars(select(Entity)).all()
        records = session.scalars(select(Record)).all()
        assert [s.name for s in sources] == [source_name]
        assert len(entities) == 1
        assert entities[0].external_key == "7"
        assert entities[0].is_active is False
        assert [(r.entity_id, r.external_key) for r in records] == [
            (entities[0].id, "42")
        ]
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
def test_archive_all_known_legacy_articles_keep_record_ids_and_skip_details(
    archive_context: tuple[Settings, ArchiveConfig],
) -> None:
    """Resolving an old member key keeps every existing record and asset."""
    settings, config = archive_context
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    repository = SqlAlchemyCollectionRepository(sessions)
    repository.persist_archive(collected_record())
    with sessions.begin() as session:
        entity = session.scalar(select(Entity))
        record = session.scalar(select(Record))
        assert entity is not None
        assert record is not None
        original_id = entity.id
        record_id = record.id
        entity.external_key = "legacy:1"
        entity.name = "Exampleauthor"
    requested: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "pages": 1,
                "items": [
                    {
                        "id": 42,
                        "url": "https://source.example/detail/42",
                        "author": "Example author",
                    }
                ],
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
    assert requested == ["/archive"]
    assert result.skipped_records == 1
    assert result.saved_records == 0
    assert result.failed_records == 0
    with sessions() as session:
        entity = session.scalar(select(Entity))
        assert entity is not None
        assert (entity.id, entity.external_key, entity.is_active) == (
            original_id,
            "7",
            False,
        )
        records = session.scalars(select(Record)).all()
        assert [(r.id, r.title, r.body) for r in records] == [
            (record_id, "Example title", "<p>Example body</p>"),
        ]
    engine.dispose()


@pytest.mark.medium
def test_archive_ambiguous_legacy_members_fail_without_requests_or_identity_changes(
    archive_context: tuple[Settings, ArchiveConfig],
) -> None:
    """Two old members with the same name cannot be silently merged."""
    settings, config = archive_context
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    with sessions.begin() as session:
        source = Source(name="source_a")
        session.add(source)
        session.flush()
        session.add_all(
            [
                Entity(
                    source_id=source.id,
                    external_key=key,
                    name="Example author",
                    is_active=False,
                )
                for key in ("legacy:1", "legacy:2")
            ]
        )
    requested: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        return httpx.Response(500)

    result = collect_archive(
        settings=settings,
        source_key="source_a",
        source_entity_key="7",
        config=config,
        repository=SqlAlchemyCollectionRepository(sessions),
        transport=httpx.MockTransport(respond),
        sleep=lambda _: None,
    )
    assert requested == []
    assert result.failed_records == 1
    assert result.failures[0].stage == "archive-identity"
    with sessions() as session:
        assert session.scalars(
            select(Entity.external_key).order_by(Entity.external_key)
        ).all() == [
            "legacy:1",
            "legacy:2",
        ]
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
        "zero-pages-with-records",
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
    elif problem in {"page-count", "zero-pages-with-records"}:
        payload["pages"] = True if problem == "page-count" else 0
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


@pytest.mark.medium
@pytest.mark.parametrize("active", [True, False])
def test_archive_previous_origin_preserves_identity_and_distinct_article_keys(
    archive_context: tuple[Settings, ArchiveConfig], *, active: bool
) -> None:
    """Previous-era articles coexist under the current member without duplicates."""
    settings, original = archive_context
    config = ArchiveConfig.model_validate(
        {
            **original.model_dump(),
            "original_base_url": "https://previous.example",
            "record_key_namespace": "previous",
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
        identity = entity.id
        entity.is_active = active
        entity.name = "Exampleauthor"
    requests: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/archive":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": 42,
                            "url": "https://previous.example/detail/42",
                            "author": "Example author",
                        }
                    ],
                    "pages": 1,
                },
            )
        return invalid_detail_response("")

    for expected_saved, expected_skipped in ((1, 0), (0, 1)):
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
        ) == (expected_saved, expected_skipped, 0)
    assert requests == ["/archive", "/article/42", "/archive"]
    with sessions() as session:
        entities = session.scalars(select(Entity)).all()
        assert [(e.id, e.external_key, e.name, e.is_active) for e in entities] == [
            (identity, "7", "Exampleauthor", active)
        ]
        records = session.scalars(select(Record).order_by(Record.external_key)).all()
        assert [(r.entity_id, r.external_key) for r in records] == [
            (identity, "42"),
            (identity, "previous:42"),
        ]
        assert records[1].source_url == "/detail/42"
    engine.dispose()


@pytest.mark.medium
def test_archive_rejects_existing_key_for_different_member(
    archive_context: tuple[Settings, ArchiveConfig],
) -> None:
    """A current member key cannot silently absorb another person's archive."""
    settings, original = archive_context
    config = ArchiveConfig.model_validate(
        {**original.model_dump(), "entity_name": "Different author"}
    )
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    repository = SqlAlchemyCollectionRepository(sessions)
    repository.persist(collected_record())
    requests: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(200, json={"items": [], "pages": 0})

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
    assert result.failures[0].stage == "archive-identity"
    assert requests == []
    with sessions() as session:
        assert session.scalar(select(Entity.name)) == "Example author"
    engine.dispose()


@pytest.mark.medium
@pytest.mark.parametrize(
    "update",
    [
        {"original_base_url": "http://previous.example"},
        {"record_key_namespace": "bad:namespace"},
        {"record_key_namespace": "nonascii-é"},
        {"record_key_namespace": ""},
        {"record_key_namespace": "x" * 33},
        {"original_record_id_pattern": "["},
        {"original_record_id_pattern": r"/detail/(\d+)"},
    ],
)
def test_archive_rejects_unsafe_origin_or_namespace(
    archive_context: tuple[Settings, ArchiveConfig], update: dict[str, str]
) -> None:
    """An alternate origin and storage namespace remain explicitly bounded."""
    _, config = archive_context
    with pytest.raises(ValidationError):
        ArchiveConfig.model_validate({**config.model_dump(), **update})


@pytest.mark.medium
@pytest.mark.parametrize("problem", ["", "host", "author", "identifier"])
def test_archive_html_details_preserve_current_identity_and_validate_origin(
    archive_context: tuple[Settings, ArchiveConfig], problem: str
) -> None:
    """Live original HTML can recover unavailable JSON without trusting other hosts."""
    settings, original = archive_context
    config = ArchiveConfig.model_validate(
        {
            **original.model_dump(),
            "detail_format": "html",
            "original_base_url": "https://previous.example",
            "record_key_namespace": "previous",
            "original_selectors": {
                **dict.fromkeys(
                    ("list_item", "detail_link", "asset", "next_page"),
                    ".unused",
                ),
                "title": ".title",
                "body": ".body",
                "published_at": ".date",
                "author": ".author",
                "entity_link": ".entity",
            },
        }
    )
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    repository = SqlAlchemyCollectionRepository(sessions)
    repository.persist(collected_record())
    with sessions() as session:
        existing_identity = session.scalar(select(Entity.id))
        assert existing_identity is not None
    requests: list[tuple[str, str]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append((request.url.host, request.url.path))
        if request.url.path == "/archive":
            host = "unapproved.example" if problem == "host" else "previous.example"
            key = "43" if problem == "identifier" else "42"
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": 42,
                            "url": f"https://{host}/detail/{key}",
                            "author": "Example author",
                        }
                    ],
                    "pages": 1,
                },
            )
        author = "Other author" if problem == "author" else "Example author"
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=f'<h1 class="title">Old article</h1>'
            '<time class="date">2020-01-01 12:00</time>'
            f'<span class="author">{author}</span>'
            '<a class="entity" href="/?entity=99">Example author</a>'
            '<div class="body"><p>Recovered</p><script>bad()</script></div>',
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
    assert result.failed_records == (1 if problem else 0)
    assert result.saved_records == (0 if problem else 1)
    assert all(host in {"archive.example", "previous.example"} for host, _ in requests)
    assert not any(path.startswith("/article/") for _, path in requests)
    if not problem:
        repeat = collect_archive(
            settings=settings,
            source_key="source_a",
            source_entity_key="7",
            config=config,
            repository=repository,
            transport=httpx.MockTransport(respond),
            sleep=lambda _: None,
        )
        assert (
            repeat.saved_records,
            repeat.skipped_records,
            repeat.failed_records,
        ) == (0, 1, 0)
        assert requests == [
            ("archive.example", "/archive"),
            ("previous.example", "/detail/42"),
            ("archive.example", "/archive"),
        ]
        with sessions() as session:
            record = session.scalar(
                select(Record).where(Record.external_key == "previous:42")
            )
            assert record is not None
            assert record.external_key == "previous:42"
            assert record.entity.external_key == "7"
            assert record.entity_id == existing_identity
            assert record.entity.is_active is True
            assert len(session.scalars(select(Entity)).all()) == 1
            assert session.scalars(
                select(Record.external_key).order_by(Record.external_key)
            ).all() == ["42", "previous:42"]
            assert "Recovered" in record.body
            assert "script" not in record.body
    engine.dispose()
