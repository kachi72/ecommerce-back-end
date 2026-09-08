"""Local identity and profile persistence."""

from datetime import datetime
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from ekumidayomi.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Role(StrEnum):
    CUSTOMER = "customer"
    ADMIN = "admin"


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (sa.UniqueConstraint("email"), sa.Index(None, "role", "is_active"))

    email: Mapped[str] = mapped_column(sa.String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(sa.String(150), default="", nullable=False)
    phone: Mapped[str | None] = mapped_column(sa.String(32))
    role: Mapped[str] = mapped_column(sa.String(20), default=Role.CUSTOMER.value, nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
