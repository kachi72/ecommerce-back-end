"""Application factory and process-lifecycle tests."""

import importlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from ekumidayomi import __version__
from ekumidayomi.core import application as application_module
from ekumidayomi.core.application import create_app
from ekumidayomi.core.settings import Settings


def test_factory_is_inert_and_uses_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    database_class = MagicMock()
    redis_factory = MagicMock()
    monkeypatch.setattr(application_module, "Database", database_class)
    monkeypatch.setattr(application_module, "create_redis_client", redis_factory)
    settings = Settings(
        _env_file=None,
        app_name="Store API",
        api_prefix="/custom/v1",
        debug=True,
    )

    app = create_app(settings)

    assert app.title == "Store API"
    assert app.version == __version__
    assert app.debug is True
    database_class.assert_not_called()
    redis_factory.assert_not_called()


def test_importing_main_does_not_construct_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_class = MagicMock()
    redis_factory = MagicMock()
    monkeypatch.setattr(application_module, "Database", database_class)
    monkeypatch.setattr(application_module, "create_redis_client", redis_factory)

    from ekumidayomi import main as main_module

    importlib.reload(main_module)

    database_class.assert_not_called()
    redis_factory.assert_not_called()


@pytest.mark.asyncio
async def test_lifespan_checks_dependencies_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = MagicMock()
    database.check_connection = AsyncMock()
    database.dispose = AsyncMock()
    redis = MagicMock()
    redis_check = AsyncMock()
    redis_close = AsyncMock()
    database_class = MagicMock(return_value=database)
    redis_factory = MagicMock(return_value=redis)
    monkeypatch.setattr(application_module, "Database", database_class)
    monkeypatch.setattr(application_module, "create_redis_client", redis_factory)
    monkeypatch.setattr(application_module, "check_redis_connection", redis_check)
    monkeypatch.setattr(application_module, "close_redis_client", redis_close)
    settings = Settings(_env_file=None)
    app = create_app(settings)

    async with app.router.lifespan_context(app):
        assert app.state.database is database
        assert app.state.redis is redis
        database.check_connection.assert_awaited_once_with()
        redis_check.assert_awaited_once_with(redis)

    database_class.assert_called_once_with(settings)
    redis_factory.assert_called_once_with(settings)
    redis_close.assert_awaited_once_with(redis)
    database.dispose.assert_awaited_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_dependency", ["postgresql", "redis"])
async def test_lifespan_fails_safely_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
    failed_dependency: str,
) -> None:
    secret_error = RuntimeError("user:password@private-host")
    database = MagicMock()
    database.check_connection = AsyncMock(
        side_effect=secret_error if failed_dependency == "postgresql" else None
    )
    database.dispose = AsyncMock()
    redis = MagicMock()
    redis_check = AsyncMock(side_effect=secret_error if failed_dependency == "redis" else None)
    redis_close = AsyncMock()
    monkeypatch.setattr(application_module, "Database", MagicMock(return_value=database))
    monkeypatch.setattr(application_module, "create_redis_client", MagicMock(return_value=redis))
    monkeypatch.setattr(application_module, "check_redis_connection", redis_check)
    monkeypatch.setattr(application_module, "close_redis_client", redis_close)
    app = create_app(Settings(_env_file=None))

    with pytest.raises(RuntimeError, match=r"^application dependency startup failed$") as exc_info:
        async with app.router.lifespan_context(app):
            pytest.fail("lifespan yielded after a failed dependency check")

    assert "password" not in str(exc_info.value)
    redis_close.assert_awaited_once_with(redis)
    database.dispose.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_redis_construction_failure_disposes_database_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = MagicMock()
    database.dispose = AsyncMock()
    redis_close = AsyncMock()
    monkeypatch.setattr(application_module, "Database", MagicMock(return_value=database))
    monkeypatch.setattr(
        application_module,
        "create_redis_client",
        MagicMock(side_effect=RuntimeError("redis://:password@private-cache/0")),
    )
    monkeypatch.setattr(application_module, "close_redis_client", redis_close)
    app = create_app(Settings(_env_file=None))

    with pytest.raises(RuntimeError, match=r"^application dependency startup failed$") as exc_info:
        async with app.router.lifespan_context(app):
            pytest.fail("lifespan yielded after Redis construction failed")

    assert "password" not in str(exc_info.value)
    redis_close.assert_not_awaited()
    database.dispose.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_database_is_disposed_when_redis_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = MagicMock()
    database.check_connection = AsyncMock()
    database.dispose = AsyncMock()
    redis = MagicMock()
    redis_check = AsyncMock()
    redis_close = AsyncMock(side_effect=RuntimeError("redis cleanup failed"))
    monkeypatch.setattr(application_module, "Database", MagicMock(return_value=database))
    monkeypatch.setattr(application_module, "create_redis_client", MagicMock(return_value=redis))
    monkeypatch.setattr(application_module, "check_redis_connection", redis_check)
    monkeypatch.setattr(application_module, "close_redis_client", redis_close)
    app = create_app(Settings(_env_file=None, check_dependencies_on_startup=False))

    with pytest.raises(RuntimeError, match="redis cleanup failed"):
        async with app.router.lifespan_context(app):
            pass

    redis_close.assert_awaited_once_with(redis)
    database.dispose.assert_awaited_once_with()
    database.check_connection.assert_not_awaited()
    redis_check.assert_not_awaited()


@pytest.mark.asyncio
async def test_factory_configures_trusted_hosts_and_cors() -> None:
    settings = Settings(
        _env_file=None,
        allowed_hosts=["api.example.com"],
        cors_origins=["https://shop.example.com"],
    )
    app = create_app(settings)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://api.example.com",
    ) as client:
        response = await client.get(
            "/health/live",
            headers={"Origin": "https://shop.example.com"},
        )
        untrusted_response = await client.get(
            "/health/live",
            headers={"Host": "untrusted.example.com"},
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://shop.example.com"
    assert response.headers["access-control-allow-credentials"] == "true"
    assert untrusted_response.status_code == 400


@pytest.mark.asyncio
async def test_wildcard_cors_does_not_allow_credentials() -> None:
    app = create_app(
        Settings(
            _env_file=None,
            cors_origins=["*"],
        )
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/health/live",
            headers={"Origin": "https://shop.example.com"},
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in response.headers


@pytest.mark.asyncio
async def test_api_root_is_versioned_while_health_routes_are_unversioned() -> None:
    app = create_app(Settings(_env_file=None, check_dependencies_on_startup=False))

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        api_response = await client.get("/api/v1/")
        health_response = await client.get("/health/live")
        versioned_health_response = await client.get("/api/v1/health/live")
        openapi_response = await client.get("/openapi.json")

    assert api_response.status_code == 200
    assert api_response.json() == {"name": "Ẹkúmidáyọ̀mí API", "version": "v1"}
    assert health_response.status_code == 200
    assert versioned_health_response.status_code == 404
    assert "/api/v1/" not in openapi_response.json()["paths"]
