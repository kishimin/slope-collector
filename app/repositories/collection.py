"""SQLAlchemy persistence implementation for collection checkpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from app.models.collection import Asset, Entity, Record, Source

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from app.config import SourceKey
    from app.scraping.domain import CollectedRecord


class SqlAlchemyCollectionRepository:
    """Save each discovered record and its assets in one transaction."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        """Bind a factory that gives each record persistence its own transaction."""
        self._sessions = sessions

    def existing_record_keys(
        self,
        source_key: SourceKey,
        entity_external_key: str,
        record_external_keys: tuple[str, ...],
    ) -> frozenset[str]:
        """Check one page of record keys before requesting detail pages."""
        if not record_external_keys:
            return frozenset()
        with self._sessions() as session:
            rows = session.scalars(
                select(Record.external_key)
                .join(Entity)
                .join(Source)
                .where(
                    Source.name == source_key,
                    Entity.external_key == entity_external_key,
                    Record.external_key.in_(record_external_keys),
                )
            )
            return frozenset(rows)

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
                entity = _find_legacy_entity(session, source.id, record)
            if entity is None:
                entity = Entity(
                    source_id=source.id,
                    external_key=record.entity_external_key,
                    name=record.private_name,
                )
                session.add(entity)
                session.flush()
            elif (
                entity.external_key != record.entity_external_key
                or entity.name != record.private_name
            ):
                entity.external_key = record.entity_external_key
                entity.name = record.private_name
                session.flush()

            existing_record = session.scalar(
                select(Record).where(
                    Record.entity_id == entity.id,
                    Record.external_key == record.external_key,
                )
            )
            if existing_record is not None:
                return False

            legacy_record = _find_legacy_record(session, source.id, record.external_key)
            if legacy_record is not None:
                legacy_entity = legacy_record.entity
                legacy_record.entity_id = entity.id
                session.flush()
                remaining_legacy_record = session.scalar(
                    select(Record.id).where(Record.entity_id == legacy_entity.id)
                )
                if remaining_legacy_record is None:
                    session.delete(legacy_entity)
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


def _find_legacy_entity(
    session: Session, source_id: int, record: CollectedRecord
) -> Entity | None:
    """Claim one pre-identity row using the strongest available old checkpoint."""
    legacy = Entity.external_key.startswith("legacy:")
    matching_record_and_name = session.scalars(
        select(Entity)
        .join(Record)
        .where(
            Entity.source_id == source_id,
            legacy,
            Entity.name == record.private_name,
            Record.external_key == record.external_key,
        )
    ).all()
    if len(matching_record_and_name) == 1:
        return matching_record_and_name[0]

    matching_record = session.scalars(
        select(Entity)
        .join(Record)
        .where(
            Entity.source_id == source_id,
            legacy,
            Record.external_key == record.external_key,
        )
    ).all()
    if len(matching_record) == 1:
        return matching_record[0]

    matching_name = session.scalars(
        select(Entity).where(
            Entity.source_id == source_id,
            legacy,
            Entity.name == record.private_name,
        )
    ).all()
    return matching_name[0] if len(matching_name) == 1 else None


def _find_legacy_record(
    session: Session, source_id: int, external_key: str
) -> Record | None:
    """Return one unambiguous checkpoint that still uses a migration key."""
    matches = session.scalars(
        select(Record)
        .join(Entity)
        .where(
            Entity.source_id == source_id,
            Entity.external_key.startswith("legacy:"),
            Record.external_key == external_key,
        )
    ).all()
    return matches[0] if len(matches) == 1 else None
