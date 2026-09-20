"""Relational persistence model for collected source records."""

from __future__ import annotations

import datetime as datetime_module  # noqa: TC003 - SQLAlchemy resolves this type at runtime.

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

IdentifierType = BigInteger().with_variant(Integer, "sqlite")


class Base(DeclarativeBase):
    """Declarative metadata shared by persisted collection records."""


class Timestamped:
    """Database-managed audit timestamps common to persisted rows."""

    created_at: Mapped[datetime_module.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False
    )
    updated_at: Mapped[datetime_module.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )


class Source(Timestamped, Base):
    """A generic configured source key without target-identifying data."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(IdentifierType, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    entities: Mapped[list[Entity]] = relationship(back_populates="source")


class Entity(Timestamped, Base):
    """An author-like source entity that owns collected records."""

    __tablename__ = "entities"
    __table_args__ = (UniqueConstraint("source_id", "external_key"),)

    id: Mapped[int] = mapped_column(IdentifierType, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False
    )
    external_key: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source: Mapped[Source] = relationship(back_populates="entities")
    records: Mapped[list[Record]] = relationship(back_populates="entity")


class Record(Timestamped, Base):
    """One sanitized article identity and its source-relative location."""

    __tablename__ = "records"
    __table_args__ = (UniqueConstraint("entity_id", "external_key"),)

    id: Mapped[int] = mapped_column(IdentifierType, primary_key=True)
    entity_id: Mapped[int] = mapped_column(
        ForeignKey("entities.id", ondelete="RESTRICT"), nullable=False
    )
    external_key: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    published_at: Mapped[datetime_module.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    entity: Mapped[Entity] = relationship(back_populates="records")
    assets: Mapped[list[Asset]] = relationship(
        back_populates="record", cascade="all, delete-orphan"
    )


class Asset(Timestamped, Base):
    """One approved source-relative image attached to a record."""

    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("record_id", "position"),)

    id: Mapped[int] = mapped_column(IdentifierType, primary_key=True)
    record_id: Mapped[int] = mapped_column(
        ForeignKey("records.id", ondelete="RESTRICT"), nullable=False
    )
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    alt_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    record: Mapped[Record] = relationship(back_populates="assets")
