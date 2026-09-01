"""Durable background-job ORM model."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from ekumidayomi.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class JobStatus(StrEnum):
    """Durable background-job lifecycle."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    RETRYING = "retrying"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A durable unit of background work and its lease state."""

    __tablename__ = "jobs"
    __table_args__ = (
        sa.UniqueConstraint("idempotency_key"),
        sa.CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        sa.CheckConstraint("max_attempts BETWEEN 1 AND 100", name="max_attempts_bounded"),
        sa.CheckConstraint("attempts <= max_attempts", name="attempts_not_above_max"),
        sa.Index(None, "status", "available_at"),
    )

    job_type: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(postgresql.JSONB, nullable=False)
    result: Mapped[dict[str, object] | None] = mapped_column(
        postgresql.JSONB,
        nullable=True,
    )
    idempotency_key: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        sa.String(20),
        nullable=False,
        server_default=sa.text("'pending'"),
    )
    attempts: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
    )
    max_attempts: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    lease_owner: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    lease_token: Mapped[UUID | None] = mapped_column(
        sa.UUID(as_uuid=True),
        nullable=True,
    )
    last_error_code: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
