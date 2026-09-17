"""Create a local Markdown preview from private source configuration."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup
from markdownify import markdownify

from app.config import load_settings, load_source_config
from app.scraping.adapter import SourceAdapter
from app.scraping.http_client import BoundedHttpClient, HttpLimits

if TYPE_CHECKING:
    from collections.abc import Sequence

    import httpx

    from app.config import Settings, SourceKey
    from app.scraping.domain import CollectedRecord


@dataclass(frozen=True, slots=True)
class PreviewResult:
    """An anonymized summary of a local preview run."""

    record_count: int
    source_results: dict[SourceKey, str]


def generate_preview(
    *,
    settings: Settings,
    source_keys: tuple[SourceKey, ...],
    output_path: Path,
    transport: httpx.BaseTransport | None = None,
) -> PreviewResult:
    """Fetch one article per source and overwrite a local Markdown artifact."""
    records: list[CollectedRecord] = []
    source_results: dict[SourceKey, str] = {}
    for source_key in source_keys:
        config = load_source_config(settings, source_key)
        adapter = SourceAdapter(source_key, config)
        limits = HttpLimits(
            connect_timeout_seconds=settings.collector_connect_timeout_seconds,
            response_timeout_seconds=settings.collector_response_timeout_seconds,
            max_response_bytes=settings.collector_max_response_bytes,
        )
        with BoundedHttpClient(
            base_url=str(config.base_url),
            user_agent=settings.collector_user_agent,
            limits=limits,
            transport=transport,
        ) as client:
            list_html = client.get_html(config.list_path.format(page=0))
            first_record = adapter.parse_list(list_html).records[0]
            detail_html = client.get_html(first_record.source_path)
            records.append(
                adapter.parse_detail(
                    detail_html,
                    source_path=first_record.source_path,
                )
            )
        source_results[source_key] = "success"

    output_path.write_text(_render_markdown(records), encoding="utf-8")
    return PreviewResult(len(records), source_results)


def _render_markdown(records: Sequence[CollectedRecord]) -> str:
    sections = ["# Scraping preview", ""]
    for record in records:
        body = BeautifulSoup(record.body_html, "html.parser")
        for image in body.find_all("img"):
            image.decompose()
        body_markdown = markdownify(str(body), heading_style="ATX").strip()
        alt_texts = [asset.alt_text for asset in record.assets if asset.alt_text]
        sections.extend(
            [
                f"## {record.source_key}",
                "",
                f"- Title: {record.title}",
                f"- Published at: {record.published_at.isoformat()}",
                f"- Author: {record.private_name}",
                f"- Images: {len(record.assets)}",
                f"- Image alt text: {', '.join(alt_texts) if alt_texts else 'None'}",
                "",
                "### Body",
                "",
                body_markdown,
                "",
            ]
        )
    return "\n".join(sections).rstrip() + "\n"


def main() -> int:
    """Generate the local user-facing preview without printing private values."""
    parser = argparse.ArgumentParser(description="Generate an anonymous scrape preview")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("scrape-preview.md"),
    )
    arguments = parser.parse_args()
    generate_preview(
        settings=load_settings(),
        source_keys=("source_a", "source_b"),
        output_path=arguments.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
