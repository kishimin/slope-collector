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
