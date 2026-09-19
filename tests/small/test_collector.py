"""Operator collection command tests."""

from types import SimpleNamespace

import pytest

from app import collector
from app.services.collection import CollectionMode, CollectionResult


@pytest.mark.small
def test_backfill_command_runs_both_configured_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The manual command delegates a full backfill to the collection workflow."""
    captured: dict[str, object] = {}

    def load_settings() -> SimpleNamespace:
        return SimpleNamespace(log_level="INFO")

    def create_session_factory(_settings: object) -> object:
        return object()

    def repository(_sessions: object) -> object:
        return object()

    monkeypatch.setattr(collector, "load_settings", load_settings)
    monkeypatch.setattr(collector, "create_session_factory", create_session_factory)
    monkeypatch.setattr(collector, "SqlAlchemyCollectionRepository", repository)

    def collect(**kwargs: object) -> CollectionResult:
        captured.update(kwargs)
        return CollectionResult(saved_records=2)

    monkeypatch.setattr(collector, "collect_all", collect)

    assert collector.main(["collect-backfill"]) == 0
    assert captured["mode"] is CollectionMode.BACKFILL
    assert captured["source_keys"] == ("source_a", "source_b")
