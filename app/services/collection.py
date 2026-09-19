"""Resumable collection workflows independent of persistence details."""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from app.config import load_source_config
from app.scraping.adapter import ParseContractError, SourceAdapter
from app.scraping.http_client import (
    BoundedHttpClient,
    FetchPermanentError,
    FetchTemporaryError,
    HttpLimits,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    import httpx

    from app.config import Settings, SourceKey
    from app.scraping.domain import CollectedRecord, ListPage

MAX_ATTEMPTS = 3


class CollectionMode(StrEnum):
    """Operator-selected extent of a collection run."""

    BACKFILL = "backfill"
    DAILY = "daily"


class CollectionRepository(Protocol):
    """Persistence checkpoint used by collection workflows."""

    def persist(self, record: CollectedRecord) -> bool:
        """Atomically save a record and its assets, returning whether it was new."""


@dataclass(frozen=True, slots=True)
class CollectionResult:
    """Observable summary for one operator collection run."""

    saved_records: int = 0
    skipped_records: int = 0
    failed_records: int = 0
    visited_pages: int = 0


def collect_all(  # noqa: C901, PLR0913 - dependencies stay explicit at the workflow boundary.
    *,
    settings: Settings,
    source_keys: tuple[SourceKey, ...],
    mode: CollectionMode,
    repository: CollectionRepository,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] | None = None,
    random_value: Callable[[], float] = random.random,
) -> CollectionResult:
    """Collect all configured source pages, using persistence as the checkpoint."""
    saved_records = 0
    skipped_records = 0
    failed_records = 0
    visited_pages = 0

    for source_key in source_keys:
        config = load_source_config(settings, source_key)
        adapter = SourceAdapter(source_key, config)
        limits = HttpLimits(
            connect_timeout_seconds=settings.collector_connect_timeout_seconds,
            response_timeout_seconds=settings.collector_response_timeout_seconds,
            max_response_bytes=settings.collector_max_response_bytes,
        )
        page_path: str | None = config.list_path.format(page=0)
        seen_pages: set[str] = set()
        stop_at_checkpoint = False

        with BoundedHttpClient(
            base_url=str(config.base_url),
            user_agent=settings.collector_user_agent,
            limits=limits,
            transport=transport,
        ) as client:

            def get_html(path: str) -> str:
                if sleep is not None:
                    sleep(request_delay_seconds(settings, random_value=random_value))
                return client.get_html(path)

            while page_path is not None and not stop_at_checkpoint:
                if page_path in seen_pages:
                    failed_records += 1
                    break
                if len(seen_pages) >= settings.collector_max_pages:
                    failed_records += 1
                    break
                seen_pages.add(page_path)
                try:
                    page = _fetch_list(get_html, adapter, page_path)
                except FetchPermanentError, FetchTemporaryError, ParseContractError:
                    failed_records += 1
                    break

                visited_pages += 1
                for reference in page.records:
                    try:
                        record = _fetch_record(get_html, adapter, reference.source_path)
                        created = repository.persist(record)
                    except (
                        FetchPermanentError,
                        FetchTemporaryError,
                        ParseContractError,
                    ):
                        failed_records += 1
                        continue

                    if created:
                        saved_records += 1
                    else:
                        skipped_records += 1
                        if mode is CollectionMode.DAILY:
                            stop_at_checkpoint = True
                            break
                page_path = page.next_path

    return CollectionResult(
        saved_records=saved_records,
        skipped_records=skipped_records,
        failed_records=failed_records,
        visited_pages=visited_pages,
    )


def _fetch_list(
    get_html: Callable[[str], str],
    adapter: SourceAdapter,
    page_path: str,
) -> ListPage:
    return _retry(lambda: adapter.parse_list(get_html(page_path)))


def _fetch_record(
    get_html: Callable[[str], str],
    adapter: SourceAdapter,
    source_path: str,
) -> CollectedRecord:
    return _retry(
        lambda: adapter.parse_detail(get_html(source_path), source_path=source_path)
    )


def _retry[T](operation: Callable[[], T]) -> T:
    """Retry only transport failures; invalid source contracts fail immediately."""
    for attempt in range(MAX_ATTEMPTS):
        try:
            return operation()
        except FetchTemporaryError:
            if attempt == MAX_ATTEMPTS - 1:
                raise
    message = "retry attempts are exhausted"
    raise RuntimeError(message)


def request_delay_seconds(
    settings: Settings, *, random_value: Callable[[], float]
) -> float:
    """Return a bounded randomized pause before one source request."""
    return (
        settings.collector_request_interval_seconds
        + settings.collector_request_jitter_seconds * random_value()
    )
