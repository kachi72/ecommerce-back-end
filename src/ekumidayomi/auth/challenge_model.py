from datetime import datetime
from enum import StrEnum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from ekumidayomi.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ChallengePurpose(StrEnum):
    REGISTRATION = "registration"
    PASSWORD_RESET = "password_reset"  # noqa: S105 -- purpose label, not a password


class PasswordCredential(TimestampMixin, Base):
    __tablename__ = "password_credentials"
    __table_args__ = (sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),)
    user_id: Mapped[UUID] = mapped_column(sa.UUID(as_uuid=True), primary_key=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(sa.String(512), nullable=False)


class EmailChallenge(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "email_challenges"
    __table_args__ = (
        sa.UniqueConstraint("email", "purpose"),
        sa.CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        sa.Index(None, "expires_at"),
    )
    email: Mapped[str] = mapped_column(sa.String(320), nullable=False)
    purpose: Mapped[str] = mapped_column(sa.String(24), nullable=False)
    key_version: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    code_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    attempts: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
