"""Shared persistence fixtures for maintenance workflows."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.collection import Base

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def control_sessions() -> Iterator[sessionmaker[Session]]:
    """Keep a local database across independently constructed applications."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    yield sessionmaker(engine)
    engine.dispose()
