"""FastAPI application factory and process lifecycle."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from ekumidayomi import __version__
from ekumidayomi.api.errors import register_error_handlers
from ekumidayomi.api.health import router as health_router
from ekumidayomi.api.middleware import RequestObservabilityMiddleware
from ekumidayomi.api.v1.router import router as api_v1_router
from ekumidayomi.core.logging import configure_logging
from ekumidayomi.core.observability import NoOpMetrics, NoOpTracer
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
    configure_logging(
        service_name=resolved_settings.service_name,
        environment=resolved_settings.app_env.value,
        level=resolved_settings.log_level.value,
        output_format=resolved_settings.log_format.value,
    )
    metrics = NoOpMetrics()
    tracer = NoOpTracer()

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
    application.state.metrics = metrics
    application.state.tracer = tracer
    register_error_handlers(application)
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
    application.add_middleware(
        RequestObservabilityMiddleware,
        metrics=metrics,
        tracer=tracer,
        trust_incoming_request_ids=resolved_settings.trust_incoming_request_ids,
    )

    application.include_router(health_router)
    application.include_router(api_v1_router, prefix=resolved_settings.api_prefix)
    return application
