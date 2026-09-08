"""Run actual migration operations without metadata.create_all masking omissions."""

from uuid import uuid4

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from ekumidayomi.core.settings import Settings
from ekumidayomi.tests.integration.conftest import set_search_path
from ekumidayomi.tests.unit.db.test_migrations import get_script_directory


def assert_session_migration_round_trip(connection: sa.Connection) -> None:
    revisions = list(reversed(list(get_script_directory().walk_revisions())))
    assert sa.inspect(connection).get_table_names() == []
    with Operations.context(MigrationContext.configure(connection)):
        for revision in revisions:
            revision.module.upgrade()
        inspector = sa.inspect(connection)
        assert "auth_sessions" in inspector.get_table_names(), (
            "S2-002 session migration is missing."
        )
        foreign_keys = inspector.get_foreign_keys("auth_sessions")
        assert len(foreign_keys) == 1
        assert foreign_keys[0]["name"] == "fk_auth_sessions_user_id_users"
        assert foreign_keys[0]["referred_table"] == "users"
        assert foreign_keys[0]["constrained_columns"] == ["user_id"]
        assert foreign_keys[0]["referred_columns"] == ["id"]
        assert foreign_keys[0]["options"]["ondelete"] == "CASCADE"
        assert any(
            item["name"] == "uq_auth_sessions_secret_hash"
            and item["column_names"] == ["secret_hash"]
            for item in inspector.get_unique_constraints("auth_sessions")
        )
        for revision in reversed(revisions):
            revision.module.downgrade()
        assert sa.inspect(connection).get_table_names() == []


async def test_session_migration_upgrade_and_downgrade(test_settings: Settings) -> None:
    engine = create_async_engine(test_settings.test_database_url, poolclass=NullPool)
    schema = f"test_session_migrations_{uuid4().hex}"
    try:
        async with engine.connect() as connection:
            await connection.execute(sa.schema.CreateSchema(schema))
            await connection.commit()
            try:
                await set_search_path(connection, schema)
                await connection.run_sync(assert_session_migration_round_trip)
                await connection.commit()
            finally:
                await connection.rollback()
                await set_search_path(connection, "public")
                await connection.execute(sa.schema.DropSchema(schema, cascade=True))
                await connection.commit()
    finally:
        await engine.dispose()
