"""Source adapter parsing contract tests."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.config import SourceConfig
from app.scraping.adapter import ParseContractError, SourceAdapter


def source_config() -> SourceConfig:
    """Return an anonymous source contract for parser tests."""
    return SourceConfig.model_validate(
        {
            "base_url": "https://source.example",
            "list_path": "/list?page={page}",
            "detail_path": "/detail/{record_id}",
            "allowed_cdn_hosts": ["cdn.example"],
            "selectors": {
                "list_item": ".entry",
                "detail_link": ".detail-link",
                "title": ".title",
                "body": ".body",
                "published_at": ".date",
                "author": ".author",
                "entity_link": ".author-link",
                "asset": ".body img",
                "next_page": ".next",
            },
            "record_id_pattern": r"/detail/(?P<record_id>\d+)",
            "entity_id_query_param": "entity",
            "published_at_format": "%Y-%m-%d %H:%M",
        }
    )


@pytest.mark.small
def test_list_parser_returns_unique_records_and_next_page() -> None:
    """List parsing exposes stable relative references without source hosts."""
    html = """
    <main>
      <article class="entry"><a class="detail-link" href="/detail/42">One</a></article>
      <article class="entry">
        <a class="detail-link" href="/detail/42">Duplicate</a>
      </article>
      <article class="entry"><a class="detail-link" href="/detail/43">Two</a></article>
      <a class="next" href="/list?page=2">Next</a>
    </main>
    """

    page = SourceAdapter("source_a", source_config()).parse_list(html)

    assert [(item.external_key, item.source_path) for item in page.records] == [
        ("42", "/detail/42"),
        ("43", "/detail/43"),
    ]
    assert page.next_path == "/list?page=2"


@pytest.mark.small
def test_detail_parser_sanitizes_body_and_normalizes_assets() -> None:
    """Detail parsing keeps useful content while removing executable markup."""
    html = """
    <article>
      <h1 class="title">  Example title  </h1>
      <time class="date">2026-09-18 12:30</time>
      <span class="author">  Example author  </span>
      <a class="author-link" href="/authors?entity=7">Profile</a>
      <div class="body" onclick="unsafe()">
        <p>Hello <strong>world</strong>.</p>
        <script>not-safe()</script>
        <img src="https://cdn.example/one.jpg" alt="One">
        <img src="https://cdn.example/two.jpg">
      </div>
    </article>
    """

    record = SourceAdapter("source_a", source_config()).parse_detail(
        html,
        source_path="/detail/42",
    )

    assert record.external_key == "42"
    assert record.entity_external_key == "7"
    assert record.private_name == "Example author"
    assert record.title == "Example title"
    assert record.published_at == datetime(2026, 9, 18, 3, 30, tzinfo=UTC)
    assert "<script" not in record.body_html
    assert "onclick" not in record.body_html
    assert "not-safe" not in record.body_html
    assert [
        (asset.source_path, asset.position, asset.alt_text) for asset in record.assets
    ] == [
        ("/one.jpg", 0, "One"),
        ("/two.jpg", 1, None),
    ]


@pytest.mark.small
def test_detail_parser_rejects_missing_required_element() -> None:
    """Missing source contracts fail closed instead of saving guessed content."""
    with pytest.raises(ParseContractError, match="required element is missing"):
        SourceAdapter("source_a", source_config()).parse_detail(
            "<article></article>",
            source_path="/detail/42",
        )


@pytest.mark.small
def test_source_configuration_rejects_non_https_hosts() -> None:
    """Collection sources cannot downgrade transport security."""
    data = source_config().model_dump(mode="json")
    data["base_url"] = "http://source.example"

    with pytest.raises(ValidationError, match="source URL must use HTTPS"):
        SourceConfig.model_validate(data)
