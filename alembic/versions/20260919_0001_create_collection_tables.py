"""Create collection checkpoint tables.

Revision ID: 20260919_0001
Revises:
Create Date: 2026-09-19
"""

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260919_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

identifier = mysql.BIGINT(unsigned=True)
timestamp = sa.DateTime()


def upgrade() -> None:
    """Create source, entity, record, and asset checkpoint tables."""
    op.create_table(
        "sources",
        sa.Column("id", identifier, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
        sa.Column(
            "created_at",
            timestamp,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            timestamp,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ),
    )
    op.create_table(
        "entities",
        sa.Column("id", identifier, primary_key=True, autoincrement=True),
        sa.Column("source_id", identifier, nullable=False),
        sa.Column("external_key", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            timestamp,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            timestamp,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("source_id", "name"),
        sa.UniqueConstraint("source_id", "external_key"),
    )
    op.create_table(
        "records",
        sa.Column("id", identifier, primary_key=True, autoincrement=True),
        sa.Column("entity_id", identifier, nullable=False),
        sa.Column("external_key", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("published_at", timestamp, nullable=False),
        sa.Column(
            "created_at",
            timestamp,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            timestamp,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("entity_id", "external_key"),
    )
    op.create_table(
        "assets",
        sa.Column("id", identifier, primary_key=True, autoincrement=True),
        sa.Column("record_id", identifier, nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("position", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("alt_text", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            timestamp,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            timestamp,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["record_id"], ["records.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("record_id", "position"),
    )


def downgrade() -> None:
    """Remove collection checkpoint tables in dependency order."""
    op.drop_table("assets")
    op.drop_table("records")
    op.drop_table("entities")
    op.drop_table("sources")
