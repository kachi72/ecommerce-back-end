"""Use the real transaction boundary inside the existing isolated test schema."""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from ekumidayomi.auth.password_policy import HibpBreachChecker
from ekumidayomi.db.uow import SqlAlchemyUnitOfWork, UnitOfWork


@pytest.fixture
async def identity_uow(database_connection: AsyncConnection) -> AsyncIterator[UnitOfWork]:
    factory = async_sessionmaker(bind=database_connection, expire_on_commit=False)
    async with SqlAlchemyUnitOfWork(factory) as uow:
        yield uow


@pytest.fixture(autouse=True)
def breach_lookup(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Fake only external lookup; registration services and local policy stay real."""

    lookup = AsyncMock(return_value=False)
    monkeypatch.setattr(HibpBreachChecker, "is_breached", lookup)
    return lookup
