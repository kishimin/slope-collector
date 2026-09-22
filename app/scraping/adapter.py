"""Configurable HTML parsing for private collection sources."""

from __future__ import annotations

import re
import unicodedata
from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

from app.scraping.domain import (
    CollectedAsset,
    CollectedRecord,
    ListPage,
    RecordReference,
)

if TYPE_CHECKING:
    from app.config import SourceConfig, SourceKey

ALLOWED_ELEMENTS = {
    "a",
    "blockquote",
    "br",
    "div",
    "em",
    "img",
    "li",
    "ol",
    "p",
    "span",
    "strong",
    "ul",
}
REMOVED_ELEMENTS = {"form", "iframe", "script", "style"}
MAX_TITLE_CHARACTERS = 500
MAX_BODY_BYTES = 1_048_576


class ParseContractError(ValueError):
    """The response does not satisfy the configured source contract."""


class SourceAdapter:
    """Parse one private source using only its injected contract."""

    def __init__(self, source_key: SourceKey, config: SourceConfig) -> None:
        """Bind an internal source key to its private extraction contract."""
        self._source_key = source_key
        self._config = config
        self._record_pattern = re.compile(config.record_id_pattern)

    def parse_list(self, html: str) -> ListPage:
        """Extract unique record references and the next page."""
        soup = BeautifulSoup(html, "html.parser")
        records: list[RecordReference] = []
        seen: set[str] = set()
        for item in soup.select(self._config.selectors.list_item):
            links = item.select(self._config.selectors.detail_link)
            if not links:
                message = "required element is missing"
                raise ParseContractError(message)
            for link in links:
                href = link.get("href") if isinstance(link, Tag) else None
                if not isinstance(href, str):
                    message = "required element is missing"
                    raise ParseContractError(message)
                source_path = self._source_path(href)
                external_key = self._record_id(source_path)
                if external_key not in seen:
                    seen.add(external_key)
                    records.append(RecordReference(external_key, source_path))

        if not records:
            message = "required element is missing"
            raise ParseContractError(message)

        next_link = soup.select_one(self._config.selectors.next_page)
        next_path = None
        next_href = next_link.get("href") if isinstance(next_link, Tag) else None
        if isinstance(next_href, str):
            next_path = self._source_path(next_href)
        return ListPage(tuple(records), next_path)

    def parse_detail(self, html: str, *, source_path: str) -> CollectedRecord:
        """Extract and validate one article from a detail response."""
        soup = BeautifulSoup(html, "html.parser")
        title_element = self._required(soup, self._config.selectors.title)
        date_element = self._required(soup, self._config.selectors.published_at)
        author_element = self._required(soup, self._config.selectors.author)
        body_element = self._required(soup, self._config.selectors.body)

        title = unicodedata.normalize("NFC", title_element.get_text()).strip()
        private_name = unicodedata.normalize("NFC", author_element.get_text()).strip()
        if not 1 <= len(title) <= MAX_TITLE_CHARACTERS or not private_name:
            message = "required text is invalid"
            raise ParseContractError(message)

        entity_link = self._entity_link(soup, private_name)
        published_at = self._published_at(date_element.get_text().strip())
        entity_external_key = self._entity_id(entity_link)
        entity_href = entity_link.get("href")
        if not isinstance(entity_href, str):
            message = "required element is missing"
            raise ParseContractError(message)
        entity_path = self._source_path(entity_href)
        canonical_path = self._source_path(source_path)
        external_key = self._record_id(canonical_path)
        assets = self._assets(body_element)
        body_html = self._sanitize_body(body_element)
        if not body_html.strip() or len(body_html.encode("utf-8")) > MAX_BODY_BYTES:
            message = "sanitized body is invalid"
            raise ParseContractError(message)

        return CollectedRecord(
            source_key=self._source_key,
            entity_external_key=entity_external_key,
            external_key=external_key,
            private_name=private_name,
            title=title,
            body_html=body_html,
            source_path=canonical_path,
            published_at=published_at,
            assets=assets,
            entity_path=entity_path,
        )

    @staticmethod
    def _required(soup: BeautifulSoup, selector: str) -> Tag:
        element = soup.select_one(selector)
        if not isinstance(element, Tag):
            message = "required element is missing"
            raise ParseContractError(message)
        return element

    def _record_id(self, source_path: str) -> str:
        match = self._record_pattern.search(source_path)
        if match is None:
            message = "record ID is invalid"
            raise ParseContractError(message)
        record_id = match.group("record_id")
        self._require_ascii_digits(record_id, "record ID")
        try:
            expected_path = self._source_path(
                self._config.detail_path.format(record_id=record_id)
            )
        except KeyError, ValueError:
            message = "detail path is invalid"
            raise ParseContractError(message) from None
        if source_path != expected_path:
            message = "detail path is invalid"
            raise ParseContractError(message)
        return record_id

    def _entity_link(self, soup: BeautifulSoup, private_name: str) -> Tag:
        candidates = [
            element
            for element in soup.select(self._config.selectors.entity_link)
            if isinstance(element, Tag)
        ]
        matching = [
            element
            for element in candidates
            if unicodedata.normalize("NFC", element.get_text()).strip() == private_name
        ]
        if len(matching) == 1:
            return matching[0]
        if len(candidates) == 1:
            return candidates[0]
        message = "entity link is missing or ambiguous"
        raise ParseContractError(message)

    def _entity_id(self, link: Tag) -> str:
        href = link.get("href")
        if not isinstance(href, str):
            message = "required element is missing"
            raise ParseContractError(message)
        query = parse_qs(urlsplit(self._source_path(href)).query)
        values = query.get(self._config.entity_id_query_param, [])
        if len(values) != 1:
            message = "entity ID is invalid"
            raise ParseContractError(message)
        entity_id = values[0]
        self._require_ascii_digits(entity_id, "entity ID")
        return entity_id

    @staticmethod
    def _require_ascii_digits(value: str, label: str) -> None:
        if not value.isascii() or not value.isdigit():
            message = f"{label} is invalid"
            raise ParseContractError(message)

    def _published_at(self, value: str) -> datetime:
        try:
            local = datetime.strptime(value, self._config.published_at_format).replace(
                tzinfo=ZoneInfo("Asia/Tokyo")
            )
        except ValueError:
            message = "published date is invalid"
            raise ParseContractError(message) from None
        return local.astimezone(UTC)

    def _assets(self, body: Tag) -> tuple[CollectedAsset, ...]:
        assets: list[CollectedAsset] = []
        for image in body.select(self._config.selectors.asset):
            source = image.get("src") if isinstance(image, Tag) else None
            if not isinstance(source, str):
                message = "asset URL is invalid"
                raise ParseContractError(message)
            alt = image.get("alt")
            assets.append(
                CollectedAsset(
                    source_path=self._asset_path(source),
                    position=len(assets),
                    alt_text=alt if isinstance(alt, str) and alt else None,
                )
            )
        return tuple(assets)

    def _sanitize_body(self, body: Tag) -> str:
        fragment = BeautifulSoup(str(body), "html.parser")
        for element in list(fragment.find_all()):
            if element.parent is None:
                continue
            if element.name in REMOVED_ELEMENTS:
                element.decompose()
                continue
            if element.name not in ALLOWED_ELEMENTS:
                element.unwrap()
                continue
            href = element.get("href")
            source = element.get("src")
            alt = element.get("alt")
            element.attrs.clear()
            if element.name == "a" and isinstance(href, str):
                # Keep the label, but never preserve an unapproved destination.
                with suppress(ParseContractError):
                    element["href"] = self._source_path(href)
            if element.name == "img" and isinstance(source, str):
                element["src"] = self._asset_path(source)
                if isinstance(alt, str):
                    element["alt"] = alt

        return unicodedata.normalize("NFC", fragment.decode_contents())

    def _source_path(self, value: str) -> str:
        return self._relative_path(value, {self._base_host})

    def _asset_path(self, value: str) -> str:
        return self._relative_path(value, set(self._config.allowed_cdn_hosts))

    @property
    def _base_host(self) -> str:
        host = urlsplit(str(self._config.base_url)).hostname
        if host is None:
            message = "source host is invalid"
            raise ParseContractError(message)
        return host.lower()

    def _relative_path(self, value: str, allowed_hosts: set[str]) -> str:
        resolved = urlsplit(urljoin(str(self._config.base_url), value))
        host = resolved.hostname.lower() if resolved.hostname else ""
        if resolved.scheme != "https" or host not in allowed_hosts:
            message = "URL leaves the approved host boundary"
            raise ParseContractError(message)
        query = parse_qs(resolved.query, keep_blank_values=True)
        query.pop("ima", None)
        flattened = [(key, item) for key, values in query.items() for item in values]
        return urlunsplit(("", "", resolved.path, urlencode(flattened), ""))
