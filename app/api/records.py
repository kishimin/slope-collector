"""Development-only views of locally collected records."""

from __future__ import annotations

import datetime as datetime_module
from typing import TYPE_CHECKING

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.models.collection import Entity, Record

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


class StoredRecordResponse(BaseModel):
    """Minimal confirmation that one record is present in local storage."""

    model_config = ConfigDict(frozen=True)

    id: int
    entity_name: str
    title: str
    published_at: datetime_module.datetime


class StoredRecordListResponse(BaseModel):
    """Bounded list of records available to the local developer."""

    model_config = ConfigDict(frozen=True)

    records: list[StoredRecordResponse]


def create_records_router(sessions: sessionmaker[Session]) -> APIRouter:
    """Build a router whose database dependency remains local to this boundary."""
    router = APIRouter()

    @router.get("/records", response_model=StoredRecordListResponse)
    async def list_records() -> StoredRecordListResponse:
        """List recent records without returning source details or article bodies."""
        with sessions() as session:
            rows = session.execute(
                select(Record.id, Entity.name, Record.title, Record.published_at)
                .join(Entity, Record.entity_id == Entity.id)
                .order_by(Record.published_at.desc(), Record.id.desc())
                .limit(100)
            ).all()
        return StoredRecordListResponse(
            records=[
                StoredRecordResponse(
                    id=record_id,
                    entity_name=entity_name,
                    title=title,
                    published_at=(
                        published_at.replace(tzinfo=datetime_module.UTC)
                        if published_at.tzinfo is None
                        else published_at
                    ),
                )
                for record_id, entity_name, title, published_at in rows
            ]
        )

    return router
