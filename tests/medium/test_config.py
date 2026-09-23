"""Environment configuration contract tests."""

from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from app.config import load_settings, load_source_config

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


@pytest.mark.medium
def test_source_configuration_is_loaded_from_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Target-specific transport and HTML contracts stay outside source code."""
    values = {
        "SOURCE_A_NAME": "Example source",
        "SOURCE_A_BASE_URL": "https://source.example",
        "SOURCE_A_LIST_PATH": "/list?page={page}",
        "SOURCE_A_DETAIL_PATH": "/detail/{record_id}",
        "SOURCE_A_ALLOWED_CDN_HOSTS": "cdn.example,media.example",
        "SOURCE_A_LIST_ITEM_SELECTOR": ".entry",
        "SOURCE_A_DETAIL_LINK_SELECTOR": ".detail",
        "SOURCE_A_TITLE_SELECTOR": ".title",
        "SOURCE_A_BODY_SELECTOR": ".body",
        "SOURCE_A_DATE_SELECTOR": ".date",
        "SOURCE_A_AUTHOR_SELECTOR": ".author",
        "SOURCE_A_ENTITY_LINK_SELECTOR": ".author-link",
        "SOURCE_A_ASSET_SELECTOR": ".body img",
        "SOURCE_A_NEXT_PAGE_SELECTOR": ".next",
        "SOURCE_A_RECORD_ID_PATTERN": r"/detail/(?P<record_id>\d+)",
        "SOURCE_A_ENTITY_ID_QUERY_PARAM": "entity",
        "SOURCE_A_PUBLISHED_AT_FORMAT": "%Y-%m-%d %H:%M",
    }
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://db/collector")
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(tmp_path)

    source = load_source_config(load_settings(), "source_a")

    assert str(source.base_url) == "https://source.example/"
    assert source.name == "Example source"
    assert source.allowed_cdn_hosts == ("cdn.example", "media.example")
    assert source.selectors.title == ".title"
    assert source.record_id_pattern == r"/detail/(?P<record_id>\d+)"


@pytest.mark.medium
def test_missing_source_configuration_does_not_leak_environment_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Incomplete private configuration fails without printing supplied values."""
    sentinel = "PRIVATE-SOURCE-HOST"
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://db/collector")
    monkeypatch.setenv("SOURCE_A_BASE_URL", f"https://{sentinel}.example")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="invalid configuration") as error:
        load_source_config(load_settings(), "source_a")

    assert sentinel not in str(error.value)


@pytest.mark.medium
def test_source_configuration_loads_from_dotenv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Private source contracts work without exporting them into the shell."""
    monkeypatch.delenv("SOURCE_A_BASE_URL", raising=False)
    dotenv = """
DATABASE_URL=mysql+pymysql://db/collector
SOURCE_A_BASE_URL=https://source.example
SOURCE_A_LIST_PATH=/list?page={page}
SOURCE_A_DETAIL_PATH=/detail/{record_id}
SOURCE_A_ALLOWED_CDN_HOSTS=cdn.example
SOURCE_A_LIST_ITEM_SELECTOR=.entry
SOURCE_A_DETAIL_LINK_SELECTOR=.detail
SOURCE_A_TITLE_SELECTOR=.title
SOURCE_A_BODY_SELECTOR=.body
SOURCE_A_DATE_SELECTOR=.date
SOURCE_A_AUTHOR_SELECTOR=.author
SOURCE_A_ENTITY_LINK_SELECTOR=.author-link
SOURCE_A_ASSET_SELECTOR=.body img
SOURCE_A_NEXT_PAGE_SELECTOR=.next
SOURCE_A_RECORD_ID_PATTERN=/detail/(?P<record_id>\\d+)
SOURCE_A_ENTITY_ID_QUERY_PARAM=entity
SOURCE_A_PUBLISHED_AT_FORMAT=%Y-%m-%d %H:%M
""".lstrip()
    (tmp_path / ".env").write_text(dotenv, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    source = load_source_config(load_settings(), "source_a")

    assert str(source.base_url) == "https://source.example/"


@pytest.mark.medium
def test_invalid_source_selector_does_not_leak_selector_value(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Invalid private selectors fail without exposing their raw value."""
    dotenv = r"""
DATABASE_URL=mysql+pymysql://db/collector
SOURCE_A_BASE_URL=https://source.example
SOURCE_A_LIST_PATH=/list?page={page}
SOURCE_A_DETAIL_PATH=/detail/{record_id}
SOURCE_A_ALLOWED_CDN_HOSTS=cdn.example
SOURCE_A_LIST_ITEM_SELECTOR=[
SOURCE_A_DETAIL_LINK_SELECTOR=.detail
SOURCE_A_TITLE_SELECTOR=.title
SOURCE_A_BODY_SELECTOR=.body
SOURCE_A_DATE_SELECTOR=.date
SOURCE_A_AUTHOR_SELECTOR=.author
SOURCE_A_ENTITY_LINK_SELECTOR=.author-link
SOURCE_A_ASSET_SELECTOR=.body img
SOURCE_A_NEXT_PAGE_SELECTOR=.next
SOURCE_A_RECORD_ID_PATTERN=/detail/(?P<record_id>\d+)
SOURCE_A_ENTITY_ID_QUERY_PARAM=entity
SOURCE_A_PUBLISHED_AT_FORMAT=%Y-%m-%d %H:%M
""".lstrip()
    (tmp_path / ".env").write_text(dotenv, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="invalid configuration") as error:
        load_source_config(load_settings(), "source_a")

    assert "[" not in str(error.value)
