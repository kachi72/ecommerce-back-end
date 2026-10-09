"""Shared HTTP auth and browser-origin boundary."""

from typing import Annotated, cast

from fastapi import Depends, Request, Response

from ekumidayomi.auth.sessions import Actor, SessionService
from ekumidayomi.auth.settings import AuthSettings
from ekumidayomi.core.dependencies import get_auth_settings
from ekumidayomi.core.settings import Settings
from ekumidayomi.db.dependencies import get_redis, get_unit_of_work
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users.errors import UntrustedOriginError


def app_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def cookie_name(settings: Settings) -> str:
    return "__Host-ekumidayomi_session" if settings.secure_cookies else "ekumidayomi_session"


def session_service(
    request: Request, config: Annotated[AuthSettings, Depends(get_auth_settings)]
) -> SessionService:
    settings = app_settings(request)
    return SessionService(get_redis(request), namespace=settings.app_env.value, settings=config)


def trusted_origin(request: Request, config: AuthSettings) -> None:
    if request.headers.get("origin") not in config.allowed_origins:
        raise UntrustedOriginError()


async def require_origin(
    request: Request, config: Annotated[AuthSettings, Depends(get_auth_settings)]
) -> None:
    trusted_origin(request, config)


async def current_actor(
    request: Request,
    uow: Annotated[UnitOfWork, Depends(get_unit_of_work)],
    sessions: Annotated[SessionService, Depends(session_service)],
    config: Annotated[AuthSettings, Depends(get_auth_settings)],
) -> Actor:
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        trusted_origin(request, config)
    return await sessions.resolve(uow, request.cookies.get(cookie_name(app_settings(request))))


def set_session_cookie(response: Response, secret: str, settings: Settings, seconds: int) -> None:
    response.set_cookie(
        cookie_name(settings),
        secret,
        max_age=seconds,
        path="/",
        secure=settings.secure_cookies,
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        cookie_name(settings),
        path="/",
        secure=settings.secure_cookies,
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"
