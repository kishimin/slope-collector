"""Manual and scheduled entry point for durable source collection."""

from __future__ import annotations

import argparse
import logging
import smtplib
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
    parsed = parser.parse_args(arguments)
    mode = (
        CollectionMode.BACKFILL
        if parsed.command == "collect-backfill"
        else CollectionMode.DAILY
    )
    settings = load_settings()
    logging.basicConfig(level=settings.log_level)
    repository = SqlAlchemyCollectionRepository(create_session_factory(settings))
    result = collect_all(
        settings=settings,
        source_keys=SOURCE_KEYS,
        mode=mode,
        repository=repository,
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
