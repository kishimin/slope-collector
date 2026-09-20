"""Runtime configuration boundary."""

import re
from typing import Literal, Self

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    Field,
    MySQLDsn,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core import InitErrorDetails
from pydantic_settings import BaseSettings, SettingsConfigDict
from soupsieve import SelectorSyntaxError
from soupsieve import compile as compile_selector

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

    @field_validator("*")
    @classmethod
    def require_valid_selector(cls, value: str) -> str:
        """Reject malformed private selectors before HTML parsing begins."""
        try:
            compile_selector(value)
        except SelectorSyntaxError:
            message = "source selector is invalid"
            raise ValueError(message) from None
        return value


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


class PrivateSourceSettings(BaseSettings):
    """Redacted raw values for one private source environment prefix."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        hide_input_in_errors=True,
    )

    base_url: SecretStr
    list_path: SecretStr
    detail_path: SecretStr
    allowed_cdn_hosts: SecretStr
    list_item_selector: SecretStr
    detail_link_selector: SecretStr
    title_selector: SecretStr
    body_selector: SecretStr
    date_selector: SecretStr
    author_selector: SecretStr
    entity_link_selector: SecretStr
    asset_selector: SecretStr
    next_page_selector: SecretStr
    record_id_pattern: SecretStr
    entity_id_query_param: SecretStr
    published_at_format: SecretStr


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
    collector_max_pages: int = 500
    collector_request_interval_seconds: float = Field(
        default=3, ge=0, allow_inf_nan=False
    )
    collector_request_jitter_seconds: float = Field(
        default=1, ge=0, allow_inf_nan=False
    )
    mail_host: str = ""
    mail_port: int = 587
    mail_username: SecretStr = SecretStr("")
    mail_password: SecretStr = SecretStr("")
    mail_from: str = ""
    mail_to: str = ""

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

    try:
        # The generated signature cannot represent a runtime environment prefix.
        private = PrivateSourceSettings(  # type: ignore[call-arg]
            _env_prefix=f"{source_key.upper()}_"
        )

        def value(field: SecretStr) -> str:
            return field.get_secret_value().strip()

        return SourceConfig.model_validate(
            {
                "base_url": value(private.base_url),
                "list_path": value(private.list_path),
                "detail_path": value(private.detail_path),
                "allowed_cdn_hosts": tuple(
                    host.strip().lower()
                    for host in value(private.allowed_cdn_hosts).split(",")
                    if host.strip()
                ),
                "selectors": {
                    "list_item": value(private.list_item_selector),
                    "detail_link": value(private.detail_link_selector),
                    "title": value(private.title_selector),
                    "body": value(private.body_selector),
                    "published_at": value(private.date_selector),
                    "author": value(private.author_selector),
                    "entity_link": value(private.entity_link_selector),
                    "asset": value(private.asset_selector),
                    "next_page": value(private.next_page_selector),
                },
                "record_id_pattern": value(private.record_id_pattern),
                "entity_id_query_param": value(private.entity_id_query_param),
                "published_at_format": value(private.published_at_format),
            }
        )
    except ValidationError, ValueError:
        message = f"invalid configuration for {source_key}"
        raise ValueError(message) from None
