"""Durable session schema and foreign-key contracts."""

from typing import cast

import sqlalchemy as sa

from ekumidayomi.auth.model import AuthSession
from ekumidayomi.db.base import Base


def test_session_user_foreign_key_contract() -> None:
    table = cast(sa.Table, AuthSession.__table__)
    constraints = list(table.foreign_key_constraints)
    assert len(constraints) == 1
    constraint = constraints[0]
    assert constraint.name == "fk_auth_sessions_user_id_users"
    assert list(constraint.columns.keys()) == ["user_id"]
    assert [element.target_fullname for element in constraint.elements] == ["users.id"]
    assert constraint.ondelete == "CASCADE"
    assert constraint.onupdate is None
    assert isinstance(table.c.user_id.type, sa.UUID)
    assert table.c.user_id.nullable is False


def test_session_schema_stores_only_digest_and_utc_lifecycle_state() -> None:
    table = cast(sa.Table, AuthSession.__table__)
    assert table.metadata is Base.metadata
    assert set(table.c.keys()) == {
        "id",
        "user_id",
        "secret_hash",
        "created_at",
        "authenticated_at",
        "expires_at",
        "revoked_at",
    }
    assert isinstance(table.c.secret_hash.type, sa.String)
    assert table.c.secret_hash.type.length == 64
    assert not table.c.secret_hash.nullable
    assert table.primary_key.name == "pk_auth_sessions"
    assert {
        (item.name, tuple(item.columns.keys()))
        for item in table.constraints
        if isinstance(item, sa.UniqueConstraint)
    } == {("uq_auth_sessions_secret_hash", ("secret_hash",))}
    assert {(item.name, tuple(item.columns.keys())) for item in table.indexes} == {
        ("ix_auth_sessions_user_id_revoked_at", ("user_id", "revoked_at")),
        ("ix_auth_sessions_expires_at", ("expires_at",)),
    }
    for name in ("created_at", "authenticated_at", "expires_at", "revoked_at"):
        column = table.c[name]
        assert isinstance(column.type, sa.DateTime)
        assert column.type.timezone
        assert column.nullable is (name == "revoked_at")
