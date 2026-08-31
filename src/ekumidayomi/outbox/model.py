"""Transactional outbox ORM model."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from ekumidayomi.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from ekumidayomi.events import DomainEvent


class OutboxStatus(StrEnum):
    """Durable delivery lifecycle."""

    PENDING = "pending"
    PROCESSING = "processing"
    PUBLISHED = "published"
    FAILED = "failed"


class OutboxMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A durable intent to publish one domain event."""

    __tablename__ = "outbox_messages"
    __table_args__ = (
        sa.UniqueConstraint("event_id"),
        sa.UniqueConstraint("idempotency_key"),
        sa.CheckConstraint("aggregate_version > 0", name="aggregate_version_positive"),
        sa.CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        sa.Index(None, "status", "available_at"),
        sa.Index(None, "aggregate_type", "aggregate_id", "aggregate_version"),
    )

    event_id: Mapped[UUID] = mapped_column(sa.UUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(sa.UUID(as_uuid=True), nullable=False)
    aggregate_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(postgresql.JSONB, nullable=False)
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
    available_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
    claimed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)

    def to_event(self) -> DomainEvent:
        """Recreate the provider-neutral event envelope."""

        return DomainEvent(
            event_id=self.event_id,
            event_type=self.event_type,
            aggregate_type=self.aggregate_type,
            aggregate_id=self.aggregate_id,
            aggregate_version=self.aggregate_version,
            occurred_at=self.occurred_at,
            payload=self.payload,
        )
