"""SQLAlchemy persistence implementation for collection checkpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from app.models.collection import Asset, Entity, Record, Source

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from app.scraping.domain import CollectedRecord


class SqlAlchemyCollectionRepository:
    """Save each discovered record and its assets in one transaction."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        """Bind a factory that gives each record persistence its own transaction."""
        self._sessions = sessions

    def persist(self, record: CollectedRecord) -> bool:
        """Return false for an existing record without duplicating its assets."""
        with self._sessions.begin() as session:
            source = session.scalar(
                select(Source).where(Source.name == record.source_key)
            )
            if source is None:
                source = Source(name=record.source_key)
                session.add(source)
                session.flush()

            entity = session.scalar(
                select(Entity).where(
                    Entity.source_id == source.id,
                    Entity.external_key == record.entity_external_key,
                )
            )
            if entity is None:
                entity = Entity(
                    source_id=source.id,
                    external_key=record.entity_external_key,
                    name=record.private_name,
                )
                session.add(entity)
                session.flush()
            elif entity.name != record.private_name:
                entity.name = record.private_name

            exists = session.scalar(
                select(Record.id).where(
                    Record.entity_id == entity.id,
                    Record.external_key == record.external_key,
                )
            )
            if exists is not None:
                return False

            stored_record = Record(
                entity_id=entity.id,
                external_key=record.external_key,
                title=record.title,
                body=record.body_html,
                source_url=record.source_path,
                published_at=record.published_at,
            )
            session.add(stored_record)
            session.flush()
            session.add_all(
                [
                    Asset(
                        record_id=stored_record.id,
                        source_url=asset.source_path,
                        position=asset.position,
                        alt_text=asset.alt_text,
                    )
                    for asset in record.assets
                ]
            )
            return True
