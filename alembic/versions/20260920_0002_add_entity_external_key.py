"""Add stable source identity to collected entities.

Revision ID: 20260920_0002
Revises: 20260919_0001
Create Date: 2026-09-20
"""

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260920_0002"
down_revision: str | None = "20260919_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

legacy_entities = sa.table(
    "entities",
    sa.column("id", sa.BigInteger()),
    sa.column("external_key", sa.String(length=255)),
)


def upgrade() -> None:
    """Add and backfill the stable identity before replacing the unique key."""
    with op.batch_alter_table("entities") as batch:
        batch.add_column(sa.Column("external_key", sa.String(255), nullable=True))

    legacy_key = sa.literal("legacy:") + sa.cast(
        legacy_entities.c.id, sa.String(length=32)
    )
    op.execute(legacy_entities.update().values(external_key=legacy_key))

    with op.batch_alter_table("entities") as batch:
        batch.alter_column(
            "external_key",
            existing_type=sa.String(length=255),
            nullable=False,
        )
        batch.create_unique_constraint(
            "uq_entities_source_external_key", ("source_id", "external_key")
        )
        batch.drop_constraint("source_id", type_="unique")


def downgrade() -> None:
    """Reject downgrade because stable identities cannot be converted safely."""
    message = (
        "downgrade is irreversible: stable entity identities cannot be restored "
        "to the legacy display-name constraint without risking duplicate entities"
    )
    raise NotImplementedError(message)
