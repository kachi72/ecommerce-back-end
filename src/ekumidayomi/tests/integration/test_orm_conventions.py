"""PostgreSQL-backed ORM convention tests."""

from datetime import datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import MetaData, String
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ekumidayomi.db.base import NAMING_CONVENTION, TimestampMixin, UUIDPrimaryKeyMixin

pytestmark = pytest.mark.integration


class ConventionBase(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class ConventionRecord(UUIDPrimaryKeyMixin, TimestampMixin, ConventionBase):
    __tablename__ = "orm_convention_records"

    name: Mapped[str] = mapped_column(String(50), nullable=False)


async def test_postgresql_generates_uuid_and_aware_timestamps(
    database_connection: AsyncConnection,
) -> None:
    await database_connection.run_sync(ConventionBase.metadata.create_all)
    session = AsyncSession(bind=database_connection, expire_on_commit=False)

    try:
        record = ConventionRecord(name="first")
        session.add(record)
        await session.commit()
        await session.refresh(record)

        assert isinstance(record.id, UUID)
        assert isinstance(record.created_at, datetime)
        assert record.created_at.tzinfo is not None
        assert record.created_at.utcoffset() == timedelta(0)
        assert record.updated_at.tzinfo is not None
        assert record.updated_at.utcoffset() == timedelta(0)
        first_updated_at = record.updated_at

        record.name = "updated"
        await session.commit()
        await session.refresh(record)

        assert record.updated_at >= first_updated_at
    finally:
        if session.in_transaction():
            await session.rollback()
        await session.close()
