"""Acceptance coverage for the local scraping preview."""

from typing import TYPE_CHECKING

import httpx
import pytest

from app.config import load_settings
from app.scraping.preview import generate_preview

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.medium
def test_operator_can_preview_an_article_without_exposing_source_configuration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An operator receives article content without source configuration details."""
    base_url = "https://source.example"
    selector_values = {
        "SOURCE_A_LIST_ITEM_SELECTOR": ".entry",
        "SOURCE_A_DETAIL_LINK_SELECTOR": ".detail-link",
        "SOURCE_A_TITLE_SELECTOR": ".title",
        "SOURCE_A_BODY_SELECTOR": ".body",
        "SOURCE_A_DATE_SELECTOR": ".date",
        "SOURCE_A_AUTHOR_SELECTOR": ".author",
        "SOURCE_A_ENTITY_LINK_SELECTOR": ".author-link",
        "SOURCE_A_ASSET_SELECTOR": ".body img",
        "SOURCE_A_NEXT_PAGE_SELECTOR": ".next",
    }
    environment = {
        "DATABASE_URL": "mysql+pymysql://db/collector",
        "COLLECTOR_USER_AGENT": "slope-collector-test/1.0 contact@example.invalid",
        "SOURCE_A_BASE_URL": base_url,
        "SOURCE_A_LIST_PATH": "/list?page={page}",
        "SOURCE_A_DETAIL_PATH": "/detail/{record_id}",
        "SOURCE_A_ALLOWED_CDN_HOSTS": "cdn.example",
        "SOURCE_A_RECORD_ID_PATTERN": r"/detail/(?P<record_id>\d+)",
        "SOURCE_A_ENTITY_ID_QUERY_PARAM": "entity",
        "SOURCE_A_PUBLISHED_AT_FORMAT": "%Y-%m-%d %H:%M",
        **selector_values,
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(tmp_path)

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/list":
            html = """
            <main><article class="entry">
              <a class="detail-link" href="/detail/42">Read</a>
            </article></main>
            """
        else:
            html = """
            <article>
              <h1 class="title">Example title</h1>
              <time class="date">2026-09-18 12:30</time>
              <span class="author">Example author</span>
              <a class="author-link" href="/authors?entity=7">Profile</a>
              <div class="body"><p>Hello <strong>world</strong>.</p>
                <script>not-safe()</script>
                <img src="https://cdn.example/image.jpg" alt="Example image">
              </div>
            </article>
            """
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=html,
        )

    output_path = tmp_path / "scrape-preview.md"
    result = generate_preview(
        settings=load_settings(),
        source_keys=("source_a",),
        output_path=output_path,
        transport=httpx.MockTransport(respond),
    )

    markdown = output_path.read_text(encoding="utf-8")
    assert result.record_count == 1
    assert result.source_results["source_a"] == "success"
    assert "Example title" in markdown
    assert "Example author" in markdown
    assert "Hello **world**." in markdown
    assert "Example image" in markdown
    assert "not-safe" not in markdown
    assert "source.example" not in markdown
    assert "cdn.example" not in markdown
    assert all(value not in markdown for value in selector_values.values())
