"""A durable pause stops outbound requests while preserving completed articles."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
import pytest

from app.config import load_settings
from app.models.control import Target
from app.repositories.control import SqlAlchemyControlRepository
from app.services.collection import CollectionMode, collect_all
from tests.medium.test_collection_reliability_integration import (
    RecordingRepository,
    configure_source,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.orm import Session, sessionmaker


@pytest.mark.medium
@pytest.mark.parametrize("mode", [CollectionMode.DAILY, CollectionMode.BACKFILL])
@pytest.mark.parametrize("pause_at", ["before", "list", "detail", "retry", "wait"])
def test_official_pause_stops_next_request_and_keeps_completed_article(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    control_sessions: sessionmaker[Session],
    mode: CollectionMode,
    pause_at: str,
) -> None:
    """Pause decisions are reread before requests, including after backoff waits."""
    configure_source(monkeypatch, tmp_path)
    controls = SqlAlchemyControlRepository(control_sessions)
    target = Target("source_a", "official")

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
        if request.url.path == "/list":
            if pause_at in {"list", "retry"}:
                pause()
            if pause_at == "retry":
                return httpx.Response(503)
            html = (
                '<article class="entry"><a class="detail" href="/detail/1">'
                'One</a><a class="detail" href="/detail/2">Two</a></article>'
            )
        else:
            if pause_at == "detail":
                pause()
            html = (
                '<h1 class="title">Title</h1><time class="date">'
                '2026-09-18 12:30</time><span class="author">Author</span>'
                '<a class="author-link" href="/author?entity=7">Author</a>'
                '<div class="body"><p>Body</p></div>'
            )
        return httpx.Response(200, headers={"content-type": "text/html"}, text=html)

    def sleep(_delay: float) -> None:
        if pause_at == "wait":
            pause()

    repository = RecordingRepository()
    result = collect_all(
        settings=load_settings(),
        source_keys=("source_a",),
        source_entity_key="7",
        mode=mode,
        repository=repository,
        transport=httpx.MockTransport(respond),
        sleep=sleep,
        controls=controls,
    )
    expected = {
        "before": [],
        "list": ["/list"],
        "detail": ["/list", "/detail/1"],
        "retry": ["/list"],
        "wait": [],
    }
    assert paths == expected[pause_at]
    assert result.saved_records == (1 if pause_at == "detail" else 0)
    assert len(repository.records) == result.saved_records
    assert result.failed_records == 0
    assert result.paused_sites == (target.key,)
