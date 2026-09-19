"""Local preview rendering tests."""

from datetime import UTC, datetime

import pytest

from app.scraping.domain import CollectedRecord
from app.scraping.preview import _render_markdown


@pytest.mark.small
def test_preview_removes_destinations_and_redacts_private_hosts() -> None:
    """Readable article text must not disclose configured source locations."""
    record = CollectedRecord(
        source_key="source_a",
        entity_external_key="7",
        external_key="42",
        private_name="Example author",
        title="Example title",
        body_html=(
            '<p><a href="/private/path">Reference</a> '
            "https://source.example/private/path</p>"
        ),
        source_path="/detail/42",
        published_at=datetime(2026, 9, 18, tzinfo=UTC),
        assets=(),
    )

    markdown = _render_markdown([record], private_hosts={"source.example"})

    assert "Reference" in markdown
    assert "source.example" not in markdown
    assert "https://" not in markdown
    assert "](" not in markdown
