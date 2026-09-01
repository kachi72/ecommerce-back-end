"""Unit tests for the durable background-job model."""

from typing import cast

import sqlalchemy as sa
from sqlalchemy.orm import Mapped

from ekumidayomi.jobs.models import Job


def test_job_uses_string_status_and_deterministic_table_names() -> None:
    table = cast(sa.Table, Job.__table__)

    assert Job.__annotations__["status"] == Mapped[str]
    assert isinstance(table.c.status.type, sa.String)
    assert not isinstance(table.c.status.type, sa.Enum)
    assert {index.name for index in table.indexes} == {"ix_jobs_status_available_at"}
    assert {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, (sa.CheckConstraint, sa.UniqueConstraint))
    } == {
        "ck_jobs_attempts_non_negative",
        "ck_jobs_attempts_not_above_max",
        "ck_jobs_max_attempts_bounded",
        "uq_jobs_idempotency_key",
    }


def test_status_has_no_database_enum_constraint() -> None:
    table = cast(sa.Table, Job.__table__)

    assert not any(
        isinstance(constraint, sa.CheckConstraint) and "status" in str(constraint.sqltext)
        for constraint in table.constraints
    )
