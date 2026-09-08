"""Use the real transaction boundary inside the existing isolated test schema."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from ekumidayomi.db.uow import SqlAlchemyUnitOfWork, UnitOfWork


@pytest.fixture
async def identity_uow(database_connection: AsyncConnection) -> AsyncIterator[UnitOfWork]:
    factory = async_sessionmaker(bind=database_connection, expire_on_commit=False)
    async with SqlAlchemyUnitOfWork(factory) as uow:
        yield uow
