"""add immutable audit records

Revision ID: 46ad9a9488c3
Revises: 734dfb7a6638
Create Date: 2026-09-02 11:02:17.655021
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "46ad9a9488c3"
down_revision: str | Sequence[str] | None = "734dfb7a6638"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create immutable audit storage and its query indexes."""

    op.create_table(
        "audit_records",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("actor_kind", sa.String(length=20), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target_type", sa.String(length=100), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name=op.f("ck_audit_records_metadata_object"),
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_audit_records"),
        ),
    )

    op.create_index(
        op.f("ix_audit_records_action_occurred_at_id"),
        "audit_records",
        ["action", "occurred_at", "id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_records_actor_id_occurred_at_id"),
        "audit_records",
        ["actor_id", "occurred_at", "id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_records_actor_kind_occurred_at_id"),
        "audit_records",
        ["actor_kind", "occurred_at", "id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_records_correlation_id"),
        "audit_records",
        ["correlation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_records_occurred_at_id"),
        "audit_records",
        ["occurred_at", "id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_records_outcome_occurred_at_id"),
        "audit_records",
        ["outcome", "occurred_at", "id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_records_target_id_occurred_at_id"),
        "audit_records",
        ["target_id", "occurred_at", "id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_records_target_type_target_id_occurred_at_id"),
        "audit_records",
        ["target_type", "target_id", "occurred_at", "id"],
        unique=False,
    )

    op.execute(
        "CREATE RULE audit_records_no_update AS ON UPDATE TO audit_records DO INSTEAD NOTHING"
    )
    op.execute(
        "CREATE RULE audit_records_no_delete AS ON DELETE TO audit_records DO INSTEAD NOTHING"
    )


def downgrade() -> None:
    """Remove audit storage, query indexes, and append-only rules."""

    op.execute("DROP RULE IF EXISTS audit_records_no_delete ON audit_records")
    op.execute("DROP RULE IF EXISTS audit_records_no_update ON audit_records")

    op.drop_index(
        op.f("ix_audit_records_target_type_target_id_occurred_at_id"),
        table_name="audit_records",
    )
    op.drop_index(
        op.f("ix_audit_records_target_id_occurred_at_id"),
        table_name="audit_records",
    )
    op.drop_index(
        op.f("ix_audit_records_outcome_occurred_at_id"),
        table_name="audit_records",
    )
    op.drop_index(
        op.f("ix_audit_records_occurred_at_id"),
        table_name="audit_records",
    )
    op.drop_index(
        op.f("ix_audit_records_correlation_id"),
        table_name="audit_records",
    )
    op.drop_index(
        op.f("ix_audit_records_actor_kind_occurred_at_id"),
        table_name="audit_records",
    )
    op.drop_index(
        op.f("ix_audit_records_actor_id_occurred_at_id"),
        table_name="audit_records",
    )
    op.drop_index(
        op.f("ix_audit_records_action_occurred_at_id"),
        table_name="audit_records",
    )
    op.drop_table("audit_records")
