"""Add the transactional outbox table.

Revision ID: 1118b82ffb5c
Revises: 0001_sprint0_baseline
Create Date: 2026-08-31 11:16:06.126777
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "1118b82ffb5c"
down_revision: str | Sequence[str] | None = "0001_sprint0_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create durable event-intent storage and its claim indexes."""

    op.create_table(
        "outbox_messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "idempotency_key",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "event_type",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "aggregate_type",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "aggregate_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "aggregate_version",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "claimed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "last_error_code",
            sa.String(length=100),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "aggregate_version > 0",
            name=op.f("ck_outbox_messages_aggregate_version_positive"),
        ),
        sa.CheckConstraint(
            "attempts >= 0",
            name=op.f("ck_outbox_messages_attempts_non_negative"),
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_outbox_messages"),
        ),
        sa.UniqueConstraint(
            "event_id",
            name=op.f("uq_outbox_messages_event_id"),
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name=op.f("uq_outbox_messages_idempotency_key"),
        ),
    )

    op.create_index(
        op.f("ix_outbox_messages_aggregate_type_aggregate_id_aggregate_version"),
        "outbox_messages",
        [
            "aggregate_type",
            "aggregate_id",
            "aggregate_version",
        ],
        unique=False,
    )

    op.create_index(
        op.f("ix_outbox_messages_status_available_at"),
        "outbox_messages",
        [
            "status",
            "available_at",
        ],
        unique=False,
    )


def downgrade() -> None:
    """Remove the outbox table and indexes."""

    op.drop_index(
        op.f("ix_outbox_messages_status_available_at"),
        table_name="outbox_messages",
    )

    op.drop_index(
        op.f("ix_outbox_messages_aggregate_type_aggregate_id_aggregate_version"),
        table_name="outbox_messages",
    )

    op.drop_table("outbox_messages")
