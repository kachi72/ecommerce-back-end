"""Session storage must be present in the owner's actual Alembic revision chain."""

from io import StringIO

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations

from ekumidayomi.tests.unit.db.test_migrations import get_script_directory


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_revision_scripts_include_session_storage(direction: str) -> None:
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
        assert "CREATE TABLE auth_sessions (" in sql, "Generate and review the S2-002 migration."
        assert "CONSTRAINT uq_auth_sessions_secret_hash UNIQUE (secret_hash)" in sql
        assert (
            "CONSTRAINT fk_auth_sessions_user_id_users FOREIGN KEY(user_id) "
            "REFERENCES users (id) ON DELETE CASCADE"
        ) in sql
        assert "CREATE INDEX ix_auth_sessions_user_id_revoked_at" in sql
        assert "CREATE INDEX ix_auth_sessions_expires_at" in sql
        assert "secret_hash VARCHAR(64) NOT NULL" in sql
    else:
        assert "DROP TABLE auth_sessions;" in sql, "The session migration must supply a downgrade."
        assert "DROP INDEX ix_auth_sessions_user_id_revoked_at;" in sql
        assert "DROP INDEX ix_auth_sessions_expires_at;" in sql
