"""Unit tests for the transactional outbox ORM model."""

from typing import cast

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped

from ekumidayomi.outbox.model import OutboxMessage


def test_status_is_a_plain_string_field_without_database_enum_options() -> None:
    table = cast(sa.Table, OutboxMessage.__table__)
    status_type = table.c.status.type

    assert OutboxMessage.__annotations__["status"] == Mapped[str]
    assert isinstance(status_type, sa.String)
    assert not isinstance(status_type, sa.Enum)
    assert status_type.length == 20
    assert not any(
        isinstance(constraint, sa.CheckConstraint) and "status" in str(constraint.sqltext)
        for constraint in table.constraints
    )

    ddl = str(
        sa.schema.CreateTable(table).compile(
            dialect=postgresql.dialect(),  # type: ignore[no-untyped-call]
        )
    )
    assert "status VARCHAR(20) DEFAULT 'pending' NOT NULL" in ddl
    assert "outbox_status" not in ddl
