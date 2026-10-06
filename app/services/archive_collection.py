"""Manual recovery of inactive histories from a privately configured JSON API."""

from __future__ import annotations

import random
import unicodedata
from datetime import datetime
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
)

from app.config import SourceSelectors, load_source_config
from app.scraping.adapter import ParseContractError, SourceAdapter
from app.scraping.http_client import (
    BoundedHttpClient,
    FetchPermanentError,
    FetchTemporaryError,
    HttpLimits,
)
from app.services.collection import (
    CollectionResult,
    _failure,
    _retry,
    wait_before_request,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    import httpx

    from app.config import Settings, SourceKey
    from app.scraping.domain import CollectedRecord


class ArchiveFields(BaseModel):
    """Private mapping from API fields to normalized record concepts."""

    model_config = ConfigDict(extra="forbid")
    records: str
    pages: str
    record_id: str
    original_url: str
    author: str
    title: str
    body: str
    published_at: str


class ArchiveConfig(BaseModel):
    """Private API contract for exactly one explicitly selected member."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    base_url: AnyHttpUrl
    list_path: str
    detail_path: str
    entity_key: str = Field(min_length=1)
    entity_name: str = Field(min_length=1, max_length=255)
    fields: ArchiveFields
    allowed_cdn_hosts: tuple[str, ...] = ()
    excluded_source_entity_keys: tuple[str, ...] = ()

    @field_validator("base_url")
    @classmethod
    def require_https(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        """Keep archive transport inside an explicit HTTPS boundary."""
        if value.scheme != "https":
            message = "archive URL must use HTTPS"
            raise ValueError(message)
        return value

    @field_validator("list_path", "detail_path")
    @classmethod
    def require_relative_path(cls, value: str) -> str:
        """Keep privately configured requests on the approved API host."""
        if not value.startswith("/") or value.startswith("//"):
            message = "archive paths must be root-relative"
            raise ValueError(message)
        return value


class ArchiveRepository(Protocol):
    """Persistence boundary that preserves inactive source identities."""

    def prepare_archive_entity(
        self, source_name: str, entity_external_key: str, entity_name: str
    ) -> None:
        """Preserve one existing member identity before detail checkpoint checks."""

    def existing_record_keys(
        self,
        source_name: str,
        entity_external_key: str,
        record_external_keys: tuple[str, ...],
    ) -> frozenset[str]:
        """Return already persisted keys before archive detail requests."""

    def persist_archive(self, record: CollectedRecord) -> bool:
        """Save one recovered article without activating its member."""


def load_archive_config(path: str) -> ArchiveConfig:
    """Read an ignored local archive contract without exposing raw errors."""
    try:
        return ArchiveConfig.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except OSError, ValueError:
        message = "archive configuration file is invalid"
        raise ValueError(message) from None


def _object(value: JsonValue) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        message = "archive response object is invalid"
        raise ParseContractError(message)
    return value


def _text(value: JsonValue) -> str:
    if not isinstance(value, str):
        message = "archive text field is invalid"
        raise ParseContractError(message)
    return value


def _key(value: JsonValue) -> str:
    key = str(value)
    if isinstance(value, bool) or not key.isascii() or not key.isdigit():
        message = "archive record identifier is invalid"
        raise ParseContractError(message)
    return key


def _require_author(value: JsonValue, expected: str) -> str:
    author = _text(value)
    if "".join(unicodedata.normalize("NFC", author).split()) != "".join(
        unicodedata.normalize("NFC", expected).split()
    ):
        message = "archive author does not match requested member"
        raise ParseContractError(message)
    return author


def collect_archive(  # noqa: C901, PLR0913 - explicit collection boundary.
    *,
    settings: Settings,
    source_key: SourceKey,
    source_entity_key: str,
    config: ArchiveConfig,
    repository: ArchiveRepository,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None],
) -> CollectionResult:
    """Supplement every archive page while preserving original checkpoints."""
    if source_entity_key in config.excluded_source_entity_keys:
        return CollectionResult()
    _key(source_entity_key)
    source = load_source_config(settings, source_key)
    try:
        repository.prepare_archive_entity(
            source.name, source_entity_key, config.entity_name
        )
    except ValueError as error:
        return CollectionResult(
            failed_records=1,
            failures=(_failure("archive-identity", source_key, error),),
        )
    # Synthetic metadata lets the existing source parser enforce the same bounds.
    selectors = SourceSelectors(
        list_item=".entry",
        detail_link=".detail",
        title=".title",
        body=".body",
        published_at=".date",
        author=".author",
        entity_link=".entity",
        asset="img",
        next_page=".next",
    )
    adapter = SourceAdapter(
        source_key,
        source.model_copy(
            update={
                "selectors": selectors,
                "published_at_format": "%Y-%m-%d %H:%M:%S",
                "allowed_cdn_hosts": (
                    *source.allowed_cdn_hosts,
                    *config.allowed_cdn_hosts,
                ),
            }
        ),
    )
    limits = HttpLimits(
        connect_timeout_seconds=settings.collector_connect_timeout_seconds,
        response_timeout_seconds=settings.collector_response_timeout_seconds,
        max_response_bytes=settings.collector_max_response_bytes,
    )
    saved = skipped = visited = 0
    failures = []
    seen: set[str] = set()
    seen_pages: set[tuple[str, ...]] = set()
    pages: int | None = None
    with BoundedHttpClient(
        base_url=str(config.base_url),
        user_agent=settings.collector_user_agent,
        limits=limits,
        transport=transport,
    ) as client:

        def fetch(path: str) -> JsonValue:
            def request() -> JsonValue:
                wait_before_request(
                    settings,
                    path,
                    sleep=sleep,
                    random_value=random.random,
                )
                return client.get_json(path)

            return _retry(request, settings=settings, sleep=sleep)

        page = 0
        while pages is None or page < pages:
            try:
                _require_page_limit(page, settings.collector_max_pages)
                payload = _object(
                    fetch(
                        config.list_path.format(entity_key=config.entity_key, page=page)
                    )
                )
                references, pages = _parse_page(
                    payload,
                    config.fields,
                    page=page,
                    previous_pages=pages,
                    max_pages=settings.collector_max_pages,
                )
                keys = tuple(_key(item[config.fields.record_id]) for item in references)
                _require_unique_page(keys, seen_pages)
                known = repository.existing_record_keys(
                    source.name, source_entity_key, keys
                )
                visited += 1
            except (
                FetchPermanentError,
                FetchTemporaryError,
                ParseContractError,
                KeyError,
                ValueError,
            ) as error:
                failures.append(_failure("archive-list", source_key, error))
                break
            for item, key in zip(references, keys, strict=True):
                try:
                    _require_author(item[config.fields.author], config.entity_name)
                    if key in seen or key in known:
                        skipped += 1
                        continue
                    seen.add(key)
                    original_url = _text(item[config.fields.original_url])
                    detail = _object(fetch(config.detail_path.format(record_id=key)))
                    _require_author(detail[config.fields.author], config.entity_name)
                    record = _parse_record(
                        detail,
                        config=config,
                        adapter=adapter,
                        entity_query=source.entity_id_query_param,
                        source_entity_key=source_entity_key,
                        original_url=original_url,
                        record_id=key,
                    )
                    if repository.persist_archive(record):
                        saved += 1
                    else:
                        skipped += 1
                except (
                    FetchPermanentError,
                    FetchTemporaryError,
                    ParseContractError,
                    KeyError,
                    ValueError,
                ) as error:
                    failures.append(_failure("archive-record", source_key, error))
            page += 1
    return CollectionResult(
        saved_records=saved,
        skipped_records=skipped,
        failed_records=len(failures),
        visited_pages=visited,
        failures=tuple(failures),
    )


def _require_page_limit(page: int, max_pages: int) -> None:
    if page >= max_pages:
        message = "archive page limit reached"
        raise ParseContractError(message)


def _require_unique_page(
    keys: tuple[str, ...],
    seen_pages: set[tuple[str, ...]],
) -> None:
    if keys and keys in seen_pages:
        message = "archive repeated a record page"
        raise ParseContractError(message)
    seen_pages.add(keys)


def _parse_page(
    payload: dict[str, JsonValue],
    fields: ArchiveFields,
    *,
    page: int,
    previous_pages: int | None,
    max_pages: int,
) -> tuple[list[dict[str, JsonValue]], int]:
    _require_page_limit(page, max_pages)
    count = payload[fields.pages]
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        message = "archive page count is invalid"
        raise ParseContractError(message)
    if previous_pages is not None and count != previous_pages:
        message = "archive page count changed during collection"
        raise ParseContractError(message)
    items = payload[fields.records]
    if not isinstance(items, list) or (count > 0 and not items):
        message = "archive record list is invalid"
        raise ParseContractError(message)
    return [_object(item) for item in items], count


def _parse_record(  # noqa: PLR0913 - source identity must remain explicit.
    detail: dict[str, JsonValue],
    *,
    config: ArchiveConfig,
    adapter: SourceAdapter,
    entity_query: str,
    source_entity_key: str,
    original_url: str,
    record_id: str,
) -> CollectedRecord:
    published = datetime.fromisoformat(_text(detail[config.fields.published_at]))
    if published.tzinfo is None:
        message = "archive publication timezone is missing"
        raise ParseContractError(message)
    date = published.astimezone(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M:%S")
    entity_url = escape("/?" + urlencode({entity_query: source_entity_key}))
    author = escape(config.entity_name)
    title = escape(_text(detail[config.fields.title]))
    html = (
        f'<h1 class="title">{title}</h1>'
        f'<time class="date">{date}</time>'
        f'<span class="author">{author}</span>'
        f'<a class="entity" href="{entity_url}">{author}</a>'
        f'<div class="body">{_text(detail[config.fields.body])}</div>'
    )
    record = adapter.parse_detail(html, source_path=original_url)
    if record.external_key != record_id:
        message = "archive original URL does not match record identifier"
        raise ParseContractError(message)
    return record
