"""PostgreSQL-backed application integration fixtures."""

from collections.abc import AsyncIterator
from uuid import uuid4

import fakeredis.aioredis
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from ekumidayomi.core.application import create_app
from ekumidayomi.core.settings import Settings
from ekumidayomi.db.base import Base
from ekumidayomi.db.dependencies import get_redis, get_session
from ekumidayomi.tests.helpers import override_dependencies


async def set_search_path(connection: AsyncConnection, search_path: str) -> None:
    """Set PostgreSQL's search path without interpolating an SQL identifier."""
    await connection.execute(
        text("SELECT set_config('search_path', :search_path, false)"),
        {"search_path": search_path},
    )


@pytest.fixture
async def database_session(test_settings: Settings) -> AsyncIterator[AsyncSession]:
    """Provide a session inside a unique disposable PostgreSQL schema."""
    schema = f"test_{uuid4().hex}"
    engine = create_async_engine(test_settings.test_database_url, poolclass=NullPool)

    try:
        try:
            connection = await engine.connect()
        except (OSError, DBAPIError):
            pytest.fail(
                "Integration PostgreSQL is unavailable; start it with "
                "`just containers-up-deps` and verify the test database URL.",
                pytrace=False,
            )

        schema_created = False
        session: AsyncSession | None = None
        try:
            await connection.execute(CreateSchema(schema))
            await connection.commit()
            schema_created = True
            connection = await connection.execution_options(
                schema_translate_map={None: schema},
            )
            await set_search_path(connection, f'"{schema}", public')
            await connection.run_sync(Base.metadata.create_all)
            await connection.commit()
            session = AsyncSession(bind=connection, expire_on_commit=False)

            yield session
        finally:
            if session is not None:
                if session.in_transaction():
                    await session.rollback()
                await session.close()
            if connection.in_transaction():
                await connection.rollback()
            if schema_created:
                await set_search_path(connection, "public")
                await connection.execute(DropSchema(schema, cascade=True))
                await connection.commit()
            await connection.close()
    finally:
        await engine.dispose()


@pytest.fixture
async def test_app(
    test_settings: Settings,
    database_session: AsyncSession,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> AsyncIterator[FastAPI]:
    """Provide the real application with scoped infrastructure overrides."""
    app = create_app(test_settings)

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield database_session

    def override_redis() -> Redis:
        return fake_redis

    with override_dependencies(
        app,
        {
            get_session: override_session,
            get_redis: override_redis,
        },
    ):
        yield app


@pytest.fixture
async def api_client(
    test_app: FastAPI,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> AsyncIterator[AsyncClient]:
    """Drive the real ASGI application without opening a network socket."""
    async with test_app.router.lifespan_context(test_app):
        test_app.state.redis = fake_redis
        transport = ASGITransport(app=test_app, raise_app_exceptions=True)
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            yield client
