"""Runtime configuration boundary."""

from typing import Literal, Self

from pydantic import (
    MySQLDsn,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core import InitErrorDetails
from pydantic_settings import BaseSettings, SettingsConfigDict


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
