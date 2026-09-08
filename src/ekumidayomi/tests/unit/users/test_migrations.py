"""The actual revision scripts must create and remove user storage."""

from io import StringIO

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations

from ekumidayomi.tests.unit.db.test_migrations import get_script_directory


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_revision_scripts_include_user_storage(direction: str) -> None:
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    revisions = list(get_script_directory().walk_revisions())
    if direction == "upgrade":
        revisions.reverse()
    with Operations.context(context):
        for revision in revisions:
            getattr(revision.module, direction)()
    sql = output.getvalue()
    if direction == "upgrade":
        assert "CREATE TABLE users (" in sql, "Generate and review the S2-001 users migration."
        assert "CONSTRAINT uq_users_email UNIQUE (email)" in sql
        assert "CREATE INDEX ix_users_role_is_active ON users (role, is_active)" in sql
        assert "role VARCHAR(20) NOT NULL" in sql
        assert "CREATE TYPE" not in sql
    else:
        assert "DROP TABLE users;" in sql, "The users migration must provide a downgrade."
        assert "DROP INDEX ix_users_role_is_active;" in sql
