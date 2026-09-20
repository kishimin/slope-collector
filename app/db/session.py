"""Database session construction at the infrastructure boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.config import Settings


def create_session_factory(settings: Settings) -> sessionmaker[Session]:
    """Create database sessions without exposing the configured URL to callers."""
    engine = create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
    )
    return sessionmaker(engine)
