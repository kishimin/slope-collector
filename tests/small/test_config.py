"""Pure configuration invariant tests."""

import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings


@pytest.mark.small
def test_production_settings_reject_debug_mode() -> None:
    """Production cannot enable framework debug behavior."""
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            debug=True,
            database_url=SecretStr("mysql+pymysql://db/collector"),
        )


@pytest.mark.small
@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
def test_settings_reject_invalid_request_interval(value: float) -> None:
    """Request pacing requires a non-negative finite base interval."""
    with pytest.raises(ValidationError):
        Settings(
            database_url=SecretStr("mysql+pymysql://db/collector"),
            collector_request_interval_seconds=value,
        )


@pytest.mark.small
@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
def test_settings_reject_invalid_request_jitter(value: float) -> None:
    """Request pacing requires a non-negative finite jitter range."""
    with pytest.raises(ValidationError):
        Settings(
            database_url=SecretStr("mysql+pymysql://db/collector"),
            collector_request_jitter_seconds=value,
        )
