"""Collection schema upgrade contract tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

import pytest
import sqlalchemy as sa

if TYPE_CHECKING:
    from types import ModuleType

    from sqlalchemy.engine import Connection


class MigrationContextFactory(Protocol):
    """Structural type for the installed Alembic context class."""

    def configure(self, connection: Connection) -> object:
        """Create a migration context for one connection."""


class OperationsFactory(Protocol):
    """Structural type for the installed Alembic operations class."""

    def __call__(self, context: object) -> object:
        """Bind schema operations to a migration context."""


def load_alembic_runtime() -> tuple[MigrationContextFactory, OperationsFactory]:
    """Import the installed runtime despite the repository script package name."""
    repository_root = Path(__file__).parents[2]
    original_path = sys.path
    sys.modules.pop("alembic", None)
    sys.path = [
        entry for entry in sys.path if Path(entry or ".").resolve() != repository_root
    ]
    try:
        migration_module = importlib.import_module("alembic.migration")
        operations_module = importlib.import_module("alembic.operations")
    finally:
        sys.path = original_path
    return cast("MigrationContextFactory", migration_module.MigrationContext), cast(
        "OperationsFactory", operations_module.Operations
    )


def load_migration(name: str) -> ModuleType:
    """Load one repository migration without importing the Alembic package path."""
    path = Path(__file__).parents[2] / "alembic" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        message = f"cannot load migration {name}"
        raise RuntimeError(message)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.medium
def test_entity_identity_upgrade_changes_an_existing_schema() -> None:
    """Databases stamped at the first revision receive stable entity identities."""
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    entities = sa.Table(
        "entities",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.UniqueConstraint("source_id", "name", name="source_id"),
    )
    metadata.create_all(engine)
    migration_context, operations = load_alembic_runtime()

    with engine.begin() as connection:
        connection.execute(
            entities.insert().values(id=1, source_id=1, name="Example author")
        )
        migration = load_migration("20260920_0002_add_entity_external_key")
        context = migration_context.configure(connection)
        migration.__dict__["op"] = operations(context)

        migration.upgrade()

        inspector = sa.inspect(connection)
        columns = {
            column["name"]: column for column in inspector.get_columns("entities")
        }
        unique_keys = {
            tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints("entities")
        }
        external_key = connection.scalar(
            sa.select(sa.column("external_key")).select_from(sa.table("entities"))
        )
        with pytest.raises(NotImplementedError, match="irreversible"):
            migration.downgrade()

    assert columns["external_key"]["nullable"] is False
    assert ("source_id", "external_key") in unique_keys
    assert ("source_id", "name") not in unique_keys
    assert external_key == "legacy:1"
    engine.dispose()
