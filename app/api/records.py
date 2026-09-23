"""Development-only read models for locally collected data."""

from __future__ import annotations

import datetime as datetime_module
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from app.models.collection import Asset, Entity, Record, Source

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


class SourceResponse(BaseModel):
    """Public source identity without target-specific configuration."""

    model_config = ConfigDict(frozen=True)

    id: int
    name: str


class EntityResponse(BaseModel):
    """Public entity metadata."""

    model_config = ConfigDict(frozen=True)

    id: int
    source_id: int
    name: str
    is_active: bool


class RecordListItem(BaseModel):
    """Record fields safe for list responses."""

    model_config = ConfigDict(frozen=True)

    id: int
    entity_id: int
    title: str
    body: str
    source_url: str
    published_at: datetime_module.datetime


class EntityRecordResponse(BaseModel):
    """Title and body returned for all records belonging to one entity."""

    model_config = ConfigDict(frozen=True)

    id: int
    title: str
    body: str


class AssetResponse(BaseModel):
    """One asset reference attached to a record."""

    model_config = ConfigDict(frozen=True)

    id: int
    source_url: str
    position: int


class RecordDetailResponse(RecordListItem):
    """Full local record including body and asset references."""

    body: str
    assets: list[AssetResponse]


class SourcesResponse(BaseModel):
    """Collection response for configured sources."""

    model_config = ConfigDict(frozen=True)

    sources: list[SourceResponse]


class EntitiesResponse(BaseModel):
    """Collection response for configured entities."""

    model_config = ConfigDict(frozen=True)

    entities: list[EntityResponse]


class PaginationResponse(BaseModel):
    """Paging metadata for record lists."""

    model_config = ConfigDict(frozen=True)

    limit: int
    offset: int
    total: int


class RecordsResponse(BaseModel):
    """Collection response for paged records."""

    model_config = ConfigDict(frozen=True)

    records: list[RecordListItem]
    pagination: PaginationResponse


class EntityRecordsResponse(BaseModel):
    """Collection response for all records belonging to one entity."""

    model_config = ConfigDict(frozen=True)

    records: list[EntityRecordResponse]


def create_records_router(  # noqa: C901
    sessions: sessionmaker[Session],
) -> APIRouter:
    """Build a local-only router backed by read-only query operations."""
    router = APIRouter()

    @router.get("/sources", response_model=SourcesResponse)
    async def list_sources() -> SourcesResponse:
        with sessions() as session:
            rows = session.scalars(select(Source).order_by(Source.id)).all()
        return SourcesResponse(
            sources=[SourceResponse(id=row.id, name=row.name) for row in rows]
        )

    @router.get("/entities", response_model=EntitiesResponse)
    async def list_entities(
        source_id: Annotated[int | None, Query(ge=1)] = None,
    ) -> EntitiesResponse:
        statement = select(Entity).order_by(Entity.id)
        if source_id is not None:
            statement = statement.where(Entity.source_id == source_id)
        with sessions() as session:
            rows = session.scalars(statement).all()
        return EntitiesResponse(entities=[_entity_response(row) for row in rows])

    @router.get("/entities/{entity_id}", response_model=EntityResponse)
    async def get_entity(entity_id: Annotated[int, Path(ge=1)]) -> EntityResponse:
        with sessions() as session:
            entity = session.get(Entity, entity_id)
        if entity is None:
            raise _not_found()
        return _entity_response(entity)

    @router.get(
        "/entities/{entity_id}/records",
        response_model=EntityRecordsResponse,
    )
    async def list_entity_records(
        entity_id: Annotated[int, Path(ge=1)],
    ) -> EntityRecordsResponse:
        with sessions() as session:
            entity = session.get(Entity, entity_id)
            if entity is None:
                raise _not_found()
            rows = session.scalars(
                select(Record)
                .where(Record.entity_id == entity_id)
                .order_by(Record.published_at.desc(), Record.id.desc())
            ).all()
        return EntityRecordsResponse(
            records=[
                EntityRecordResponse(id=row.id, title=row.title, body=row.body)
                for row in rows
            ]
        )

    @router.get("/records", response_model=RecordsResponse)
    async def list_records(
        entity_id: Annotated[int | None, Query(ge=1)] = None,
        from_date: Annotated[datetime_module.date | None, Query(alias="from")] = None,
        to_date: Annotated[datetime_module.date | None, Query(alias="to")] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> RecordsResponse:
        if from_date is not None and to_date is not None and from_date > to_date:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "BAD_REQUEST",
                    "message": "The start date must not be after the end date.",
                },
            )
        statement = select(Record).order_by(
            Record.published_at.desc(), Record.id.desc()
        )
        count_statement = select(func.count(Record.id))
        if entity_id is not None:
            statement = statement.where(Record.entity_id == entity_id)
            count_statement = count_statement.where(Record.entity_id == entity_id)
        if from_date is not None:
            statement = statement.where(Record.published_at >= from_date)
            count_statement = count_statement.where(Record.published_at >= from_date)
        if to_date is not None:
            end = datetime_module.datetime.combine(
                to_date, datetime_module.time.max, tzinfo=datetime_module.UTC
            )
            statement = statement.where(Record.published_at <= end)
            count_statement = count_statement.where(Record.published_at <= end)
        statement = statement.offset(offset).limit(limit)
        with sessions() as session:
            rows = session.scalars(statement).all()
            total = session.scalar(count_statement) or 0
        return RecordsResponse(
            records=[_record_list_response(row) for row in rows],
            pagination=PaginationResponse(limit=limit, offset=offset, total=total),
        )

    @router.get("/records/{record_id}", response_model=RecordDetailResponse)
    async def get_record(record_id: Annotated[int, Path(ge=1)]) -> RecordDetailResponse:
        with sessions() as session:
            record = session.get(Record, record_id)
            assets = (
                session.scalars(
                    select(Asset)
                    .where(Asset.record_id == record_id)
                    .order_by(Asset.position, Asset.id)
                ).all()
                if record is not None
                else []
            )
        if record is None:
            raise _not_found()
        return RecordDetailResponse(
            **_record_list_response(record).model_dump(),
            assets=[
                AssetResponse(
                    id=asset.id, source_url=asset.source_url, position=asset.position
                )
                for asset in assets
            ],
        )

    return router


def _entity_response(entity: Entity) -> EntityResponse:
    return EntityResponse(
        id=entity.id,
        source_id=entity.source_id,
        name=entity.name,
        is_active=entity.is_active,
    )


def _record_list_response(record: Record) -> RecordListItem:
    return RecordListItem(
        id=record.id,
        entity_id=record.entity_id,
        title=record.title,
        body=record.body,
        source_url=record.source_url,
        published_at=_as_utc(record.published_at),
    )


def _as_utc(value: datetime_module.datetime) -> datetime_module.datetime:
    return value.replace(tzinfo=datetime_module.UTC) if value.tzinfo is None else value


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "NOT_FOUND",
            "message": "Requested resource does not exist.",
        },
    )
