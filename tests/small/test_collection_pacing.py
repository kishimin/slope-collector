"""Source request pacing tests."""

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from app.services.collection import request_delay_seconds, wait_before_request

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


@pytest.mark.small
def test_wait_before_request_logs_path_and_delay_outside_production(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Development operators can observe each paced source request."""
    settings = cast(
        "Settings",
        SimpleNamespace(
            environment="development",
            collector_request_interval_seconds=3,
            collector_request_jitter_seconds=1,
        ),
    )
    observed_delays: list[float] = []

    with caplog.at_level("INFO"):
        wait_before_request(
            settings,
            "/detail/42",
            sleep=observed_delays.append,
            random_value=lambda: 0.5,
        )

    assert observed_delays == [3.5]
    assert (
        "waiting before source request path=/detail/42 delay_seconds=3.50"
        in caplog.text
    )


@pytest.mark.small
def test_wait_before_request_does_not_log_in_production(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Production keeps pacing without emitting per-request progress logs."""
    settings = cast(
        "Settings",
        SimpleNamespace(
            environment="production",
            collector_request_interval_seconds=3,
            collector_request_jitter_seconds=1,
        ),
    )

    with caplog.at_level("INFO"):
        wait_before_request(
            settings,
            "/detail/42",
            sleep=lambda _: None,
            random_value=lambda: 0.5,
        )

    assert "waiting before source request" not in caplog.text
