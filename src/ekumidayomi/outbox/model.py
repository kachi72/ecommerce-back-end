"""Transactional outbox ORM model."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from ekumidayomi.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from ekumidayomi.events import DomainEvent


class OutboxStatus(StrEnum):
    """Durable delivery lifecycle."""

    PENDING = "pending"
    PROCESSING = "processing"
    PUBLISHED = "published"
    FAILED = "failed"


def outbox_status_values(enum: type[OutboxStatus]) -> list[str]:
    """Persist enum values rather than Python member names."""

    return [member.value for member in enum]


class OutboxMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A durable intent to publish one domain event."""

    __tablename__ = "outbox_messages"
    __table_args__ = (
        UniqueConstraint("event_id"),
        UniqueConstraint("idempotency_key"),
        CheckConstraint("aggregate_version > 0", name="aggregate_version_positive"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        CheckConstraint(
            "(status = 'processing' AND claimed_at IS NOT NULL AND published_at IS NULL) "
            "OR (status = 'published' AND claimed_at IS NULL AND published_at IS NOT NULL) "
            "OR (status IN ('pending', 'failed') AND claimed_at IS NULL AND published_at IS NULL)",
            name="status_timestamps_consistent",
        ),
        Index(None, "status", "available_at"),
        Index(None, "aggregate_type", "aggregate_id", "aggregate_version"),
    )

    event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    aggregate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    status: Mapped[OutboxStatus] = mapped_column(
        Enum(
            OutboxStatus,
            name="outbox_status",
            values_callable=outbox_status_values,
            validate_strings=True,
        ),
        nullable=False,
        server_default=text("'pending'::outbox_status"),
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)

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
