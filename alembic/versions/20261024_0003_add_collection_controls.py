"""Persist maintenance controls without modifying collected records.

Revision ID: 20261024_0003
Revises: 20260920_0002
"""

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20261024_0003"
down_revision: str | None = "20260920_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create separate durable controls for official and archive sites."""
    op.create_table(
        "collection_controls",
        sa.Column("target", sa.String(32), primary_key=True),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("resume_mode", sa.String(16), nullable=False),
        sa.Column("check_interval_minutes", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(255)),
        sa.Column("next_check_at", sa.DateTime()),
        sa.Column("last_checked_at", sa.DateTime()),
        sa.Column("last_check_succeeded", sa.Boolean()),
        sa.Column("last_check_error", sa.String(255)),
        sa.Column("revision", sa.String(36), nullable=False),
    )


def downgrade() -> None:
    """Remove controls while preserving source and article data."""
    op.drop_table("collection_controls")
