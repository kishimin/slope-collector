"""Runtime configuration boundary."""

import os
import re
from typing import Literal, Self

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    MySQLDsn,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core import InitErrorDetails
from pydantic_settings import BaseSettings, SettingsConfigDict

SourceKey = Literal["source_a", "source_b"]


class SourceSelectors(BaseModel):
    """HTML extraction boundaries supplied by private configuration."""

    list_item: str
    detail_link: str
    title: str
    body: str
    published_at: str
    author: str
    entity_link: str
    asset: str
    next_page: str


class SourceConfig(BaseModel):
    """Validated private configuration for one collection source."""

    base_url: AnyHttpUrl
    list_path: str
    detail_path: str
    allowed_cdn_hosts: tuple[str, ...]
    selectors: SourceSelectors
    record_id_pattern: str
    entity_id_query_param: str
    published_at_format: str

    @field_validator("base_url")
    @classmethod
    def require_https(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        """Disallow collection over plaintext transport."""
        if value.scheme != "https":
            message = "source URL must use HTTPS"
            raise ValueError(message)
        return value

    @field_validator("list_path", "detail_path")
    @classmethod
    def require_relative_path(cls, value: str) -> str:
        """Keep source hosts isolated to the validated base URL."""
        if not value.startswith("/") or value.startswith("//"):
            message = "source paths must be root-relative"
            raise ValueError(message)
        return value

    @field_validator("allowed_cdn_hosts")
    @classmethod
    def require_cdn_hosts(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Require an explicit outbound image-host allowlist."""
        if not value or any(not host or "/" in host for host in value):
            message = "approved CDN hosts are required"
            raise ValueError(message)
        return value

    @field_validator("record_id_pattern")
    @classmethod
    def require_named_record_id(cls, value: str) -> str:
        """Ensure record identifiers can be extracted without site logic."""
        try:
            pattern = re.compile(value)
        except re.error:
            message = "record ID pattern must be valid"
            raise ValueError(message) from None
        if "record_id" not in pattern.groupindex:
            message = "record ID pattern must define record_id"
            raise ValueError(message)
        return value


class Settings(BaseSettings):
    """Validated settings loaded from the process environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        hide_input_in_errors=True,
    )

    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: SecretStr
    collector_user_agent: str = ""
    collector_connect_timeout_seconds: float = 10
    collector_response_timeout_seconds: float = 30
    collector_max_response_bytes: int = 5_242_880

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        """Reject database URLs that cannot use the installed driver."""
        try:
            database_url = MySQLDsn(value.get_secret_value())
        except ValidationError:
            message = "database URL must be a valid MySQL URL"
            raise ValueError(message) from None
        if database_url.scheme != "mysql+pymysql":
            message = "database URL must use mysql+pymysql"
            raise ValueError(message)
        return value

    @model_validator(mode="after")
    def reject_production_debug_mode(self) -> Self:
        """Reject framework diagnostics in production."""
        if self.environment == "production" and self.debug:
            message = "debug mode must be disabled in production"
            raise ValueError(message)
        return self


def load_settings() -> Settings:
    """Load and validate settings from the runtime environment."""
    # The generated type signature cannot represent environment-provided fields.
    try:
        return Settings()  # type: ignore[call-arg]
    except ValidationError as error:
        sanitized_errors: list[InitErrorDetails] = []
        for detail in error.errors(include_url=False):
            sanitized_error = InitErrorDetails(
                type=detail["type"],
                loc=detail["loc"],
                input=SecretStr(""),
            )
            if context := detail.get("ctx"):
                sanitized_error["ctx"] = context
            sanitized_errors.append(sanitized_error)
        raise ValidationError.from_exception_data(
            error.title,
            sanitized_errors,
            hide_input=True,
        ) from None


def load_source_config(settings: Settings, source_key: SourceKey) -> SourceConfig:
    """Load one private source contract without retaining raw errors."""
    del settings  # Settings establishes the validated runtime environment boundary.
    prefix = source_key.upper()

    def required(name: str) -> str:
        value = os.environ.get(f"{prefix}_{name}", "").strip()
        if not value:
            message = f"incomplete configuration for {source_key}"
            raise ValueError(message)
        return value

    try:
        return SourceConfig.model_validate(
            {
                "base_url": required("BASE_URL"),
                "list_path": required("LIST_PATH"),
                "detail_path": required("DETAIL_PATH"),
                "allowed_cdn_hosts": tuple(
                    host.strip().lower()
                    for host in required("ALLOWED_CDN_HOSTS").split(",")
                    if host.strip()
                ),
                "selectors": {
                    "list_item": required("LIST_ITEM_SELECTOR"),
                    "detail_link": required("DETAIL_LINK_SELECTOR"),
                    "title": required("TITLE_SELECTOR"),
                    "body": required("BODY_SELECTOR"),
                    "published_at": required("DATE_SELECTOR"),
                    "author": required("AUTHOR_SELECTOR"),
                    "entity_link": required("ENTITY_LINK_SELECTOR"),
                    "asset": required("ASSET_SELECTOR"),
                    "next_page": required("NEXT_PAGE_SELECTOR"),
                },
                "record_id_pattern": required("RECORD_ID_PATTERN"),
                "entity_id_query_param": required("ENTITY_ID_QUERY_PARAM"),
                "published_at_format": required("PUBLISHED_AT_FORMAT"),
            }
        )
    except ValidationError, ValueError:
        message = f"invalid configuration for {source_key}"
        raise ValueError(message) from None
