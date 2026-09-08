"""Execute real revision operations in an empty disposable PostgreSQL schema."""

from uuid import uuid4

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from ekumidayomi.core.settings import Settings
from ekumidayomi.tests.integration.conftest import set_search_path
from ekumidayomi.tests.unit.db.test_migrations import get_script_directory


def assert_revision_round_trip(connection: sa.Connection) -> None:
    """Check upgrade/downgrade operations without metadata.create_all masking gaps."""
    revisions = list(reversed(list(get_script_directory().walk_revisions())))
    assert sa.inspect(connection).get_table_names() == []
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        for revision in revisions:
            revision.module.upgrade()
        inspector = sa.inspect(connection)
        assert "users" in inspector.get_table_names(), "S2-001 users migration is missing."
        constraints = inspector.get_unique_constraints("users")
        assert any(
            item["name"] == "uq_users_email" and item["column_names"] == ["email"]
            for item in constraints
        )
        assert any(
            item["name"] == "ix_users_role_is_active"
            and item["column_names"] == ["role", "is_active"]
            for item in inspector.get_indexes("users")
        )
        columns = {item["name"]: item for item in inspector.get_columns("users")}
        assert isinstance(columns["role"]["type"], sa.String)
        assert not isinstance(columns["role"]["type"], sa.Enum)
        for revision in reversed(revisions):
            revision.module.downgrade()
        assert sa.inspect(connection).get_table_names() == []


async def test_user_migration_upgrade_and_downgrade(test_settings: Settings) -> None:
    engine = create_async_engine(test_settings.test_database_url, poolclass=NullPool)
    schema = f"test_user_migrations_{uuid4().hex}"
    try:
        async with engine.connect() as connection:
            await connection.execute(sa.schema.CreateSchema(schema))
            await connection.commit()
            try:
                # No public fallback: a pre-existing users table cannot make this pass.
                await set_search_path(connection, schema)
                await connection.run_sync(assert_revision_round_trip)
                await connection.commit()
            finally:
                await connection.rollback()
                await set_search_path(connection, "public")
                await connection.execute(sa.schema.DropSchema(schema, cascade=True))
                await connection.commit()
    finally:
        await engine.dispose()
