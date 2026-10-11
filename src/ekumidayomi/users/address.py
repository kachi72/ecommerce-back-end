"""Customer address book."""

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from ekumidayomi.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Address(TimestampMixin, UUIDPrimaryKeyMixin, Base):
    __tablename__ = "user_addresses"
    __table_args__ = (
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.Index(None, "user_id", "kind", unique=True, postgresql_where=sa.text("is_default")),
    )

    user_id: Mapped[UUID] = mapped_column(sa.UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    recipient: Mapped[str] = mapped_column(sa.String(150), nullable=False)
    line1: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    line2: Mapped[str | None] = mapped_column(sa.String(200))
    city: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    region: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    postal_code: Mapped[str | None] = mapped_column(sa.String(20))
    country_code: Mapped[str] = mapped_column(sa.String(2), nullable=False)
    phone: Mapped[str | None] = mapped_column(sa.String(32))
    is_default: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
