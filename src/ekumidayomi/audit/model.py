"""Append-only business audit persistence model."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, Mapper, mapped_column

from ekumidayomi.db.base import Base, UUIDPrimaryKeyMixin


class ActorKind(StrEnum):
    """Actor categories that do not depend on the future user model."""

    CUSTOMER = "customer"
    ADMINISTRATOR = "administrator"
    SYSTEM = "system"
    ANONYMOUS = "anonymous"


class AuditOutcome(StrEnum):
    """Stable outcomes recorded for an attempted business action."""

    SUCCEEDED = "succeeded"
    DENIED = "denied"
    FAILED = "failed"


class AuditRecord(UUIDPrimaryKeyMixin, Base):
    """Immutable evidence of one business action and its safe context."""

    __tablename__ = "audit_records"
    __table_args__ = (
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name="metadata_object",
        ),
        sa.Index(None, "occurred_at", "id"),
        sa.Index(None, "action", "occurred_at", "id"),
        sa.Index(None, "actor_kind", "occurred_at", "id"),
        sa.Index(None, "actor_id", "occurred_at", "id"),
        sa.Index(None, "outcome", "occurred_at", "id"),
        sa.Index(None, "target_id", "occurred_at", "id"),
        sa.Index(None, "target_type", "target_id", "occurred_at", "id"),
        sa.Index(None, "correlation_id"),
    )

    actor_kind: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(sa.UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    target_id: Mapped[UUID] = mapped_column(sa.UUID(as_uuid=True), nullable=False)
    outcome: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
    )
    correlation_id: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    metadata_: Mapped[dict[str, object]] = mapped_column(
        "metadata",
        postgresql.JSONB,
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    )


@sa.event.listens_for(AuditRecord, "before_update")
def _prevent_audit_update(
    mapper: Mapper[AuditRecord],
    connection: sa.Connection,
    target: AuditRecord,
) -> None:
    """Reject ORM updates even before the database append-only rule runs."""

    del mapper, connection, target
    raise sa.exc.InvalidRequestError("audit records are append-only")


@sa.event.listens_for(AuditRecord, "before_delete")
def _prevent_audit_delete(
    mapper: Mapper[AuditRecord],
    connection: sa.Connection,
    target: AuditRecord,
) -> None:
    """Reject ORM deletes even before the database append-only rule runs."""

    del mapper, connection, target
    raise sa.exc.InvalidRequestError("audit records are append-only")
