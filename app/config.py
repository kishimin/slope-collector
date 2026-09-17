"""Runtime configuration boundary."""

from typing import Literal

from pydantic import SecretStr  # noqa: TC002 -- Pydantic resolves it at runtime.
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


def load_settings() -> Settings:
    """Load and validate settings from the runtime environment."""
    # The generated type signature cannot represent environment-provided fields.
    return Settings()  # type: ignore[call-arg]
