"""Operator collection command tests."""

import logging
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


@pytest.mark.small
def test_daily_command_selects_incremental_collection_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scheduled command delegates to the incremental workflow."""
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        collector,
        "load_settings",
        lambda: SimpleNamespace(log_level="INFO"),
    )
    monkeypatch.setattr(
        collector,
        "create_session_factory",
        lambda _settings: object(),
    )
    monkeypatch.setattr(
        collector,
        "SqlAlchemyCollectionRepository",
        lambda _sessions: object(),
    )

    def collect(**kwargs: object) -> CollectionResult:
        captured.update(kwargs)
        return CollectionResult()

    monkeypatch.setattr(collector, "collect_all", collect)

    assert collector.main(["collect-daily"]) == 0
    assert captured["mode"] is CollectionMode.DAILY


@pytest.mark.small
def test_collection_command_suppresses_http_client_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configured debug logging cannot disclose private source locations."""
    configured_loggers: dict[str, int] = {}

    class ExternalLogger:
        def __init__(self, name: str) -> None:
            self._name = name

        def setLevel(self, level: int) -> None:  # noqa: N802 - logging interface.
            configured_loggers[self._name] = level

    def load_settings() -> SimpleNamespace:
        return SimpleNamespace(log_level="DEBUG")

    monkeypatch.setattr(collector, "load_settings", load_settings)
    monkeypatch.setattr(collector, "create_session_factory", lambda _settings: object())
    monkeypatch.setattr(
        collector,
        "SqlAlchemyCollectionRepository",
        lambda _sessions: object(),
    )
    monkeypatch.setattr(
        collector,
        "collect_all",
        lambda **_kwargs: CollectionResult(),
    )
    original_get_logger = logging.getLogger

    def get_logger(name: str | None = None) -> ExternalLogger | logging.Logger:
        if name in {"httpcore", "httpx"}:
            return ExternalLogger(name)
        return original_get_logger(name)

    monkeypatch.setattr(logging, "getLogger", get_logger)

    assert collector.main(["collect-backfill"]) == 0
    assert configured_loggers == {
        "httpcore": logging.WARNING,
        "httpx": logging.WARNING,
    }
