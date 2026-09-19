"""Source request pacing tests."""

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from app.services.collection import request_delay_seconds

if TYPE_CHECKING:
    from app.config import Settings


@pytest.mark.small
def test_request_delay_combines_interval_and_bounded_jitter() -> None:
    """Configured pacing avoids synchronized request bursts across collectors."""
    settings = cast(
        "Settings",
        SimpleNamespace(
            collector_request_interval_seconds=3,
            collector_request_jitter_seconds=1,
        ),
    )

    expected_delay = 3.5
    assert request_delay_seconds(settings, random_value=lambda: 0.5) == expected_delay
