"""Durable application sessions; never provider tokens."""

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from ekumidayomi.db.base import Base, UUIDPrimaryKeyMixin


class AuthSession(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("secret_hash"),
        sa.Index(None, "user_id", "revoked_at"),
        sa.Index(None, "expires_at"),
    )

    user_id: Mapped[UUID] = mapped_column(sa.UUID(as_uuid=True), nullable=False)
    secret_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    authenticated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
