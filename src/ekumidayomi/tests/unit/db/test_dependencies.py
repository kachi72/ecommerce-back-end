"""FastAPI infrastructure dependency tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest
from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from ekumidayomi.db.dependencies import get_redis, get_session


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


def test_get_redis_returns_application_client() -> None:
    redis = MagicMock(spec=Redis)
    request = build_request(MagicMock(), redis)

    assert get_redis(request) is redis
