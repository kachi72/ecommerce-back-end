"""Schema contracts checked without opening a database connection."""

from typing import cast

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.schema import ScalarElementColumnDefault

from ekumidayomi.auth.challenge_model import ChallengePurpose, EmailChallenge, PasswordCredential
from ekumidayomi.db.base import Base
from ekumidayomi.users.model import User


def test_credentials_have_one_table_level_cascading_foreign_key() -> None:
    table = cast(sa.Table, PasswordCredential.__table__)
    assert table.metadata is Base.metadata
    assert list(table.primary_key.columns.keys()) == ["user_id"]
    assert table.primary_key.name == "pk_password_credentials"
    constraints = list(table.foreign_key_constraints)
    assert len(constraints) == 1
    foreign_key = constraints[0]
    assert foreign_key in PasswordCredential.__table_args__
    assert foreign_key.name == "fk_password_credentials_user_id_users"
    assert foreign_key.ondelete == "CASCADE"
    assert foreign_key.onupdate is None
    assert list(foreign_key.columns.keys()) == ["user_id"]
    assert foreign_key.elements[0].column is User.__table__.c.id
    assert isinstance(table.c.password_hash.type, sa.String)
    assert table.c.password_hash.type.length == 512
    assert not table.c.password_hash.nullable
    for name in ("created_at", "updated_at"):
        column_type = table.c[name].type
        assert isinstance(column_type, sa.DateTime) and column_type.timezone
        assert not table.c[name].nullable
        assert table.c[name].server_default is not None


def test_purpose_constants_are_strings_without_database_enum_restrictions() -> None:
    assert {purpose.value for purpose in ChallengePurpose} == {"registration", "password_reset"}
    assert all(isinstance(purpose, str) for purpose in ChallengePurpose)
    table = cast(sa.Table, EmailChallenge.__table__)
    assert type(table.c.purpose.type) is sa.String
    assert table.c.purpose.type.length == 24
    assert not table.c.purpose.nullable
    dialect_type = cast(type[sa.engine.Dialect], postgresql.dialect)
    ddl = str(sa.schema.CreateTable(table).compile(dialect=dialect_type()))
    assert "purpose VARCHAR(24) NOT NULL" in ddl
    assert "registration" not in ddl and "password_reset" not in ddl


def test_challenge_constraints_and_index_use_shared_naming_convention() -> None:
    table = cast(sa.Table, EmailChallenge.__table__)
    assert table.metadata is Base.metadata
    unique = [item for item in table.constraints if isinstance(item, sa.UniqueConstraint)]
    assert len(unique) == 1
    assert unique[0].name == "uq_email_challenges_email_purpose"
    assert list(unique[0].columns.keys()) == ["email", "purpose"]
    checks = [item for item in table.constraints if isinstance(item, sa.CheckConstraint)]
    assert len(checks) == 1
    assert checks[0].name == "ck_email_challenges_attempts_non_negative"
    assert str(checks[0].sqltext) == "attempts >= 0"
    indexes = list(table.indexes)
    assert len(indexes) == 1
    assert indexes[0].name == "ix_email_challenges_expires_at"
    assert list(indexes[0].columns.keys()) == ["expires_at"]
    assert not indexes[0].unique


def test_challenge_defaults_and_timestamp_nullability() -> None:
    table = cast(sa.Table, EmailChallenge.__table__)
    assert list(table.primary_key.columns.keys()) == ["id"]
    assert table.c.id.default is not None
    default = table.c.attempts.default
    assert isinstance(default, ScalarElementColumnDefault)
    assert default.arg == 0
    assert not table.c.attempts.nullable
    for name in ("created_at", "expires_at", "consumed_at"):
        column_type = table.c[name].type
        assert isinstance(column_type, sa.DateTime) and column_type.timezone
        assert table.c[name].nullable is (name == "consumed_at")
