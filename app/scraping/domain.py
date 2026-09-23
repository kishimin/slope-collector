"""Source-neutral records produced by scraping adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from app.config import SourceKey


@dataclass(frozen=True, slots=True)
class RecordReference:
    """A source-relative record discovered on a list page."""

    external_key: str
    source_path: str


@dataclass(frozen=True, slots=True)
class ListPage:
    """Unique record references and an optional next page."""

    records: tuple[RecordReference, ...]
    next_path: str | None


@dataclass(frozen=True, slots=True)
class CollectedAsset:
    """An approved source-relative asset."""

    source_path: str
    position: int
    alt_text: str | None


@dataclass(frozen=True, slots=True)
class CollectedRecord:
    """A validated source-neutral article."""

    source_key: SourceKey
    entity_external_key: str
    external_key: str
    private_name: str
    title: str
    body_html: str
    source_path: str
    published_at: datetime
    assets: tuple[CollectedAsset, ...]
    entity_path: str = ""
    source_name: str = ""
