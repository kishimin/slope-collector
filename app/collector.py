"""Manual and scheduled entry point for durable source collection."""

from __future__ import annotations

import argparse
import logging
import smtplib
import time
from typing import TYPE_CHECKING

from app.config import load_settings
from app.db.session import create_session_factory
from app.repositories.collection import SqlAlchemyCollectionRepository
from app.services.collection import CollectionMode, collect_all
from app.services.notifications import notify_failures

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.config import SourceKey
LOGGER = logging.getLogger(__name__)
SOURCE_KEYS: tuple[SourceKey, ...] = ("source_a", "source_b")


def main(arguments: Sequence[str] | None = None) -> int:
    """Run a configured collection mode and return a process exit status."""
    parser = argparse.ArgumentParser(description="Collect configured source records")
    parser.add_argument(
        "command",
        choices=("collect-backfill", "collect-daily"),
    )
    parser.add_argument(
        "--source-entity-key",
        help="Collect one source-owned member identity during a backfill.",
    )
    parser.add_argument(
        "--source",
        choices=SOURCE_KEYS,
        help="Run collection for one configured source.",
    )
    parsed = parser.parse_args(arguments)
    if parsed.source_entity_key is not None and parsed.source is None:
        parser.error("--source-entity-key requires --source")
    if parsed.source_entity_key is not None and parsed.command != "collect-backfill":
        parser.error("--source-entity-key requires collect-backfill")
    mode = (
        CollectionMode.BACKFILL
        if parsed.command == "collect-backfill"
        else CollectionMode.DAILY
    )
    settings = load_settings()
    logging.basicConfig(level=settings.log_level)
    for logger_name in ("httpcore", "httpx"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    repository = SqlAlchemyCollectionRepository(create_session_factory(settings))
    source_keys = (parsed.source,) if parsed.source is not None else SOURCE_KEYS
    result = collect_all(
        settings=settings,
        source_keys=source_keys,
        source_entity_key=parsed.source_entity_key,
        mode=mode,
        repository=repository,
        sleep=time.sleep,
    )
    try:
        notify_failures(settings, result)
    except OSError, smtplib.SMTPException:
        LOGGER.exception("collection failure notification could not be sent")
    LOGGER.info(
        "collection completed saved=%d skipped=%d failed=%d pages=%d",
        result.saved_records,
        result.skipped_records,
        result.failed_records,
        result.visited_pages,
    )
    return 1 if result.failed_records else 0


if __name__ == "__main__":
    raise SystemExit(main())
