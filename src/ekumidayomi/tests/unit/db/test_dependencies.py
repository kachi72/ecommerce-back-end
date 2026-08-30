"""FastAPI infrastructure dependency tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from ekumidayomi.db.dependencies import get_redis, get_session, get_unit_of_work


def build_request(database: object, redis: object) -> Request:
    request = MagicMock(spec=Request)
    request.app.state.database = database
    request.app.state.redis = redis
    return request


@pytest.mark.asyncio
async def test_get_session_yields_application_database_session() -> None:
    session = MagicMock(spec=AsyncSession)

    @asynccontextmanager
    async def session_context() -> AsyncIterator[AsyncSession]:
        yield session

    database = MagicMock()
    database.session = session_context
    request = build_request(database, MagicMock())

    yielded = [item async for item in get_session(request)]

    assert yielded == [session]


@pytest.mark.asyncio
async def test_get_unit_of_work_owns_one_session_and_rolls_back_on_exit() -> None:
    session = MagicMock(spec=AsyncSession)
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    session.in_transaction.return_value = False
    factory = MagicMock(return_value=session)
    database = MagicMock()
    database.session_factory = factory
    request = build_request(database, MagicMock())

    yielded = [item async for item in get_unit_of_work(request)]

    assert len(yielded) == 1
    factory.assert_called_once_with()
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once_with()
    session.close.assert_awaited_once_with()


def test_get_redis_returns_application_client() -> None:
    redis = MagicMock(spec=Redis)
    request = build_request(MagicMock(), redis)

    assert get_redis(request) is redis
