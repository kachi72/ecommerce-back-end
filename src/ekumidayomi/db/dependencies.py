"""FastAPI infrastructure dependencies."""

from collections.abc import AsyncIterator
from typing import cast

from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from ekumidayomi.db.session import Database


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Provide one rollback-safe session per request."""
    database = cast(Database, request.app.state.database)
    async with database.session() as session:
        yield session


def get_redis(request: Request) -> Redis:
    """Return the application-owned Redis client."""
    return cast(Redis, request.app.state.redis)
