"""Database checkpoint contract tests."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.collection import Asset, Base, Entity, Record, Source
from app.repositories.collection import SqlAlchemyCollectionRepository
from app.scraping.domain import CollectedAsset, CollectedRecord


def collected_record() -> CollectedRecord:
    """Return an anonymous parsed record with one approved asset."""
    return CollectedRecord(
        source_key="source_a",
        entity_external_key="7",
        external_key="42",
        private_name="Example author",
        title="Example title",
        body_html="<p>Example body</p>",
        source_path="/detail/42",
        published_at=datetime(2026, 9, 18, tzinfo=UTC),
        assets=(CollectedAsset(source_path="/asset/1", position=0, alt_text="Image"),),
    )


@pytest.mark.medium
def test_repository_saves_record_assets_once_in_one_checkpoint() -> None:
    """A repeated collection preserves one source, entity, record, and asset."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    repository = SqlAlchemyCollectionRepository(sessions)

    assert repository.persist(collected_record()) is True
    assert repository.persist(collected_record()) is False

    with sessions() as session:
        assert len(session.scalars(select(Source)).all()) == 1
        assert len(session.scalars(select(Entity)).all()) == 1
        assert len(session.scalars(select(Record)).all()) == 1
        assets = session.scalars(select(Asset)).all()
        assert [
            (asset.position, asset.source_url, asset.alt_text) for asset in assets
        ] == [(0, "/asset/1", "Image")]
    engine.dispose()


@pytest.mark.medium
def test_repository_uses_source_entity_identifier_for_checkpoint() -> None:
    """Display-name collisions and changes preserve distinct stable identities."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    repository = SqlAlchemyCollectionRepository(sessions)
    first = collected_record()
    same_name = replace(
        first,
        entity_external_key="8",
        external_key="43",
        source_path="/detail/43",
    )
    renamed = replace(first, private_name="Updated author")

    assert repository.persist(first) is True
    assert repository.persist(same_name) is True
    assert repository.persist(renamed) is False

    with sessions() as session:
        expected_record_count = 2
        entities = session.scalars(select(Entity).order_by(Entity.external_key)).all()
        assert [(entity.external_key, entity.name) for entity in entities] == [
            ("7", "Updated author"),
            ("8", "Example author"),
        ]
        assert len(session.scalars(select(Record)).all()) == expected_record_count
    engine.dispose()


@pytest.mark.medium
def test_repository_claims_migrated_entity_without_duplicate() -> None:
    """The first collection after upgrade preserves its existing checkpoint."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    first = collected_record()
    with sessions.begin() as session:
        source = Source(name=first.source_key)
        session.add(source)
        session.flush()
        entity = Entity(
            source_id=source.id,
            external_key="legacy:1",
            name=first.private_name,
        )
        session.add(entity)
        session.flush()
        session.add(
            Record(
                entity_id=entity.id,
                external_key=first.external_key,
                title=first.title,
                body=first.body_html,
                source_url=first.source_path,
                published_at=first.published_at,
            )
        )

    repository = SqlAlchemyCollectionRepository(sessions)

    assert repository.persist(first) is False
    with sessions() as session:
        entities = session.scalars(select(Entity)).all()
        records = session.scalars(select(Record)).all()
        assert [(entity.external_key, entity.name) for entity in entities] == [
            ("7", "Example author")
        ]
        assert len(records) == 1
    engine.dispose()


@pytest.mark.medium
def test_repository_reconciles_renamed_entity_after_new_record() -> None:
    """Newest-first collection still recognizes an older migrated checkpoint."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    first = collected_record()
    with sessions.begin() as session:
        source = Source(name=first.source_key)
        session.add(source)
        session.flush()
        entity = Entity(
            source_id=source.id,
            external_key="legacy:1",
            name=first.private_name,
        )
        session.add(entity)
        session.flush()
        session.add(
            Record(
                entity_id=entity.id,
                external_key=first.external_key,
                title=first.title,
                body=first.body_html,
                source_url=first.source_path,
                published_at=first.published_at,
            )
        )

    repository = SqlAlchemyCollectionRepository(sessions)
    renamed_new = replace(
        first,
        private_name="Updated author",
        external_key="43",
        source_path="/detail/43",
    )
    renamed_old = replace(first, private_name="Updated author")

    assert repository.persist(renamed_new) is True
    assert repository.persist(renamed_old) is False
    with sessions() as session:
        entities = session.scalars(select(Entity)).all()
        records = session.scalars(select(Record).order_by(Record.external_key)).all()
        assert [(entity.external_key, entity.name) for entity in entities] == [
            ("7", "Updated author")
        ]
        assert [record.external_key for record in records] == ["42", "43"]
    engine.dispose()
