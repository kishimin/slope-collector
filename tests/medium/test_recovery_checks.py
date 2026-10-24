"""Recovery validates a list and one article without adding stored records."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
import pytest
from sqlalchemy import func, select

from app.config import load_settings
from app.models.collection import Record
from app.models.control import Target
from app.repositories.control import SqlAlchemyControlRepository
from app.services.control import run_recovery_checks
from tests.medium.test_collection_reliability_integration import configure_source

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.orm import Session, sessionmaker


@pytest.mark.medium
@pytest.mark.parametrize("problem", [None, "list", "detail", "503"])
def test_official_recovery_checks_one_article_without_persisting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    control_sessions: sessionmaker[Session],
    problem: str | None,
) -> None:
    """HTTP 200 maintenance pages keep the pause; valid parsing releases it."""
    configure_source(monkeypatch, tmp_path)
    manifest = tmp_path / ".env.recovery.json"
    manifest.write_text(
        json.dumps([{"source": "source_a", "site": "official"}]), encoding="utf-8"
    )
    monkeypatch.setenv("COLLECTOR_RECOVERY_CONFIG_PATH", str(manifest))
    controls = SqlAlchemyControlRepository(control_sessions)
    target = Target("source_a", "official")
    now = datetime(2026, 10, 24, tzinfo=UTC)
    controls.pause(target, resume_mode="automatic", interval=60, reason=None, now=now)
    paths: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if problem == "503":
            return httpx.Response(503)
        if request.url.path == "/list":
            html = (
                '<article class="entry"><a class="detail" href="/detail/1">'
                'One</a><a class="detail" href="/detail/2">Two</a></article>'
            )
        else:
            html = (
                '<h1 class="title">Title</h1><time class="date">'
                '2026-09-18 12:30</time><span class="author">Author</span>'
                '<a class="author-link" href="/author?entity=7">Author</a>'
                '<div class="body"><p>Body</p></div>'
            )
        if (problem == "list" and request.url.path == "/list") or (
            problem == "detail" and request.url.path != "/list"
        ):
            html = "<h1>Maintenance</h1>"
        return httpx.Response(200, headers={"content-type": "text/html"}, text=html)

    result = run_recovery_checks(
        settings=load_settings(),
        repository=controls,
        now=lambda: now + timedelta(hours=1),
        transport=httpx.MockTransport(respond),
        sleep=lambda _: None,
    )
    assert paths == (
        ["/list"] if problem in {"list", "503"} else ["/list", "/detail/1"]
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
        assert session.scalar(select(func.count()).select_from(Record)) == 0


@pytest.mark.medium
def test_recovery_worker_cannot_claim_an_inflight_short_interval_check(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    control_sessions: sessionmaker[Session],
) -> None:
    """A one-minute interval cannot overlap a check whose HTTP deadline is longer."""
    configure_source(monkeypatch, tmp_path)
    manifest = tmp_path / ".env.recovery.json"
    manifest.write_text('[{"source":"source_a","site":"official"}]', encoding="utf-8")
    monkeypatch.setenv("COLLECTOR_RECOVERY_CONFIG_PATH", str(manifest))
    monkeypatch.setenv("COLLECTOR_RESPONSE_TIMEOUT_SECONDS", "90")
    controls = SqlAlchemyControlRepository(control_sessions)
    target = Target("source_a", "official")
    now = datetime(2026, 10, 24, tzinfo=UTC)
    controls.pause(target, resume_mode="automatic", interval=1, reason=None, now=now)
    second_claims: list[int] = []

    def respond(_request: httpx.Request) -> httpx.Response:
        other = run_recovery_checks(
            settings=load_settings(),
            repository=controls,
            now=lambda: now + timedelta(minutes=2),
            sleep=lambda _: None,
            transport=httpx.MockTransport(lambda _: httpx.Response(503)),
        )
        second_claims.append(other.checked)
        return httpx.Response(503)

    run_recovery_checks(
        settings=load_settings(),
        repository=controls,
        now=lambda: now + timedelta(minutes=1),
        sleep=lambda _: None,
        transport=httpx.MockTransport(respond),
    )
    assert second_claims == [0]
