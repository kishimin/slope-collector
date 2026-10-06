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
from app.services.archive_collection import collect_archive, load_archive_config
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
    parser.add_argument(
        "--archive-config",
        help="Private JSON archive contract for a targeted manual backfill.",
    )
    parsed = parser.parse_args(arguments)
    if parsed.source_entity_key is not None and parsed.source is None:
        parser.error("--source-entity-key requires --source")
    if parsed.source_entity_key is not None and parsed.command != "collect-backfill":
        parser.error("--source-entity-key requires collect-backfill")
    if parsed.archive_config is not None and (
        parsed.command != "collect-backfill" or parsed.source_entity_key is None
    ):
        parser.error("--archive-config requires a targeted collect-backfill")
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
    if parsed.archive_config is not None:
        try:
            archive_config = load_archive_config(parsed.archive_config)
        except ValueError as error:
            parser.error(str(error))
        result = collect_archive(
            settings=settings,
            source_key=parsed.source,
            source_entity_key=parsed.source_entity_key,
            config=archive_config,
            repository=repository,
            sleep=time.sleep,
        )
    else:
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
