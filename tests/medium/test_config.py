"""Environment configuration contract tests."""

import pytest
from pydantic import ValidationError
from pytest import MonkeyPatch

from app.config import Settings


@pytest.mark.medium
def test_settings_read_environment_without_exposing_database_url(
    monkeypatch: MonkeyPatch,
) -> None:
    """Runtime settings load deployment values while keeping secrets redacted."""
    database_url = "mysql+pymysql://db/collector"
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DATABASE_URL", database_url)

    settings = Settings(_env_file=None)

    assert settings.environment == "test"
    assert settings.debug is False
    assert settings.database_url.get_secret_value() == database_url
    assert database_url not in repr(settings)


@pytest.mark.medium
def test_settings_reject_missing_database_url(monkeypatch: MonkeyPatch) -> None:
    """A process cannot start with an unspecified persistence boundary."""
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
