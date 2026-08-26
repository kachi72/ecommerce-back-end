"""Health endpoint tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ekumidayomi.api.health import router


def build_health_app(database: MagicMock, redis: MagicMock) -> FastAPI:
    """Build a small app with explicit health-check dependencies."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.database = database
        app.state.redis = redis
        yield

    application = FastAPI(lifespan=lifespan)
    application.include_router(router)
    return application


@pytest.mark.asyncio
async def test_liveness_does_not_query_dependencies() -> None:
    database = MagicMock()
    database.check_connection = AsyncMock()
    redis = MagicMock()
    redis.ping = AsyncMock()
    app = build_health_app(database, redis)

    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    database.check_connection.assert_not_awaited()
    redis.ping.assert_not_awaited()


@pytest.mark.asyncio
async def test_readiness_reports_healthy_dependencies() -> None:
    database = MagicMock()
    database.check_connection = AsyncMock()
    redis = MagicMock()
    redis.ping = AsyncMock(return_value=True)
    app = build_health_app(database, redis)

    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"postgresql": "ok", "redis": "ok"},
    }
    database.check_connection.assert_awaited_once_with()
    redis.ping.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_readiness_safely_reports_postgresql_failure() -> None:
    database = MagicMock()
    database.check_connection = AsyncMock(
        side_effect=RuntimeError("postgresql://user:password@private-host/database")
    )
    redis = MagicMock()
    redis.ping = AsyncMock(return_value=True)
    app = build_health_app(database, redis)

    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "service_not_ready",
            "checks": {"postgresql": "failed", "redis": "ok"},
        }
    }
    assert "password" not in response.text
    assert "private-host" not in response.text
    redis.ping.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_readiness_safely_reports_redis_failure() -> None:
    database = MagicMock()
    database.check_connection = AsyncMock()
    redis = MagicMock()
    redis.ping = AsyncMock(side_effect=RuntimeError("redis://:password@private-cache/0"))
    app = build_health_app(database, redis)

    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "service_not_ready",
            "checks": {"postgresql": "ok", "redis": "failed"},
        }
    }
    assert "password" not in response.text
    assert "private-cache" not in response.text
    database.check_connection.assert_awaited_once_with()
