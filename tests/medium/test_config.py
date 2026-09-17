"""Environment configuration contract tests."""

from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from app.config import load_settings

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.medium
def test_settings_read_environment_without_exposing_database_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Runtime settings load deployment values while keeping secrets redacted."""
    database_url = "mysql+pymysql://db/collector"
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.chdir(tmp_path)

    settings = load_settings()

    assert settings.environment == "test"
    assert settings.debug is False
    assert settings.database_url.get_secret_value() == database_url
    assert database_url not in repr(settings)


@pytest.mark.medium
def test_settings_reject_missing_database_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A process cannot start with an unspecified persistence boundary."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValidationError):
        load_settings()


@pytest.mark.medium
@pytest.mark.parametrize(
    "database_url",
    [
        "",
        "not-a-database-url",
        "mysql://db/collector",
        "mysql+asyncmy://db/collector",
    ],
)
def test_settings_reject_unusable_database_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    database_url: str,
) -> None:
    """A process cannot start with an unusable persistence boundary."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValidationError):
        load_settings()


@pytest.mark.medium
def test_settings_do_not_expose_invalid_database_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Validation errors do not reveal database credentials."""
    sentinel = "LEAKME"
    database_url = f"postgresql://collector:{sentinel}@db/collector"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValidationError) as error:
        load_settings()

    assert sentinel not in str(error.value)
    assert sentinel not in error.value.json()
