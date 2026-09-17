"""Runtime configuration boundary."""

from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated settings loaded from the process environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: SecretStr

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
    return Settings()  # type: ignore[call-arg]
