"""FastAPI application factory and process lifecycle."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from ekumidayomi import __version__
from ekumidayomi.api.health import router as health_router
from ekumidayomi.api.v1.router import router as api_v1_router
from ekumidayomi.core.redis import (
    check_redis_connection,
    close_redis_client,
    create_redis_client,
)
from ekumidayomi.core.settings import Settings, get_settings
from ekumidayomi.db.session import Database


def create_app(settings: Settings | None = None) -> FastAPI:
    """Construct an application without opening infrastructure connections."""
    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        database = Database(resolved_settings)
        try:
            redis = create_redis_client(resolved_settings)
        except Exception as exc:
            await database.dispose()
            raise RuntimeError("application dependency startup failed") from exc

        application.state.database = database
        application.state.redis = redis

        try:
            if resolved_settings.check_dependencies_on_startup:
                try:
                    await database.check_connection()
                    await check_redis_connection(redis)
                except Exception as exc:
                    raise RuntimeError("application dependency startup failed") from exc
            yield
        finally:
            try:
                await close_redis_client(redis)
            finally:
                await database.dispose()

    application = FastAPI(
        title=resolved_settings.app_name,
        version=__version__,
        debug=resolved_settings.debug,
        lifespan=lifespan,
    )
    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=resolved_settings.allowed_hosts,
    )
    if resolved_settings.cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=resolved_settings.cors_origins,
            allow_credentials="*" not in resolved_settings.cors_origins,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Accept", "Authorization", "Content-Type", "X-Request-ID"],
        )

    application.include_router(health_router)
    application.include_router(api_v1_router, prefix=resolved_settings.api_prefix)
    return application
