"""Create the empty Sprint 0 schema baseline.

Revision ID: 0001_sprint0_baseline
Revises: None
"""

from collections.abc import Sequence

revision: str = "0001_sprint0_baseline"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create no domain tables in Sprint 0."""
    pass


def downgrade() -> None:
    """Remove no domain tables in Sprint 0."""
    pass
