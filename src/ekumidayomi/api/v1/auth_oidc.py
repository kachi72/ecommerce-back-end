"""Browser-bound OIDC redirects that terminate in durable local sessions."""

import secrets
import time
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from ekumidayomi.auth.dependencies import (
    app_settings,
    cookie_name,
    current_actor,
    require_origin,
    session_service,
    set_session_cookie,
)
from ekumidayomi.auth.oidc import schemas as oidc_schemas
from ekumidayomi.auth.oidc.attempts import AttemptStore, state_hash
from ekumidayomi.auth.oidc.contracts import Attempt, Provider
from ekumidayomi.auth.oidc.providers import OidcProvider
from ekumidayomi.auth.oidc.service import (
    finish,
    list_identities,
    record_failed_handshake,
    unlink,
)
from ekumidayomi.auth.oidc.settings import ProviderName
from ekumidayomi.auth.permissions import Permission, authorize
from ekumidayomi.auth.sessions import Actor, SessionService
from ekumidayomi.db.dependencies import get_redis, get_unit_of_work
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users.errors import AuthenticationRequiredError, ExternalLoginFailedError

router = APIRouter(prefix="/auth/oidc", tags=["authentication"])
Uow = Annotated[UnitOfWork, Depends(get_unit_of_work)]
Sessions = Annotated[SessionService, Depends(session_service)]
CurrentActor = Annotated[Actor, Depends(current_actor)]
ReturnPath = Literal["/", "/profile", "/shop"]
Intent = Literal["login", "link", "reauthenticate"]


def provider_registry(request: Request) -> dict[ProviderName, Provider]:
    """Construct enabled adapters from the application-owned settings object."""

    config = app_settings(request).auth.oidc
    registry: dict[ProviderName, Provider] = {}
    for name in ProviderName:
        provider_config = getattr(config, name.value)
        if provider_config.enabled:
            registry[name] = OidcProvider(name, provider_config, config.http_timeout_seconds)
    return registry


def browser_cookie(request: Request) -> str:
    """Use the host-only prefix whenever secure cookies are enabled."""

    if app_settings(request).secure_cookies:
        return "__Host-ekumidayomi_oidc"
    return "ekumidayomi_oidc"


def attempt_store(request: Request) -> AttemptStore:
    settings = app_settings(request)
    return AttemptStore(
        get_redis(request),
        namespace=settings.app_env.value,
        ttl=settings.auth.oidc.attempt_seconds,
    )


async def begin(
    request: Request,
    provider: ProviderName,
    *,
    intent: Intent,
    actor: Actor | None = None,
    return_path: ReturnPath = "/profile",
) -> RedirectResponse:
    """Persist a one-time attempt before redirecting to an enabled provider."""

    adapter = provider_registry(request).get(provider)
    if adapter is None:
        raise ExternalLoginFailedError()
    browser = secrets.token_urlsafe(32)
    oidc = app_settings(request).auth.oidc
    provider_config = getattr(oidc, provider.value)
    attempt = Attempt(
        provider=provider,
        intent=intent,
        browser_hash=state_hash(browser),
        nonce=secrets.token_urlsafe(32),
        verifier=secrets.token_urlsafe(64),
        redirect_uri=provider_config.redirect_uri,
        return_path=return_path,
        actor_id=actor.user_id if actor else None,
        session_id=actor.session_id if actor else None,
        started_at=int(time.time()),
    )
    state = await attempt_store(request).create(attempt)
    url = await adapter.authorization_url(state, attempt)
    response = RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)
    response.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    response.set_cookie(
        browser_cookie(request),
        browser,
        max_age=oidc.attempt_seconds,
        secure=app_settings(request).secure_cookies,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


@router.post(
    "/{provider}/start",
    dependencies=[Depends(require_origin)],
    status_code=status.HTTP_303_SEE_OTHER,
)
async def start(
    provider: ProviderName,
    request: Request,
    return_path: ReturnPath = "/profile",
) -> RedirectResponse:
    return await begin(request, provider, intent="login", return_path=return_path)


@router.post("/{provider}/link", status_code=status.HTTP_303_SEE_OTHER)
async def link(
    provider: ProviderName,
    request: Request,
    actor: CurrentActor,
    uow: Uow,
    sessions: Sessions,
) -> RedirectResponse:
    await authorize(
        uow,
        actor,
        Permission.PROFILE_WRITE,
        recent_seconds=sessions.settings.recent_auth_seconds,
    )
    return await begin(request, provider, intent="link", actor=actor)


@router.post("/{provider}/reauthenticate", status_code=status.HTTP_303_SEE_OTHER)
async def reauthenticate_provider(
    provider: ProviderName,
    request: Request,
    actor: CurrentActor,
    uow: Uow,
) -> RedirectResponse:
    await authorize(uow, actor, Permission.PROFILE_WRITE)
    return await begin(request, provider, intent="reauthenticate", actor=actor)


@router.get("/{provider}/callback", status_code=status.HTTP_303_SEE_OTHER)
async def callback(
    provider: ProviderName,
    request: Request,
    uow: Uow,
    sessions: Sessions,
    state: Annotated[str, Query(min_length=20, max_length=128)],
    code: Annotated[str | None, Query(max_length=4096)] = None,
    error: Annotated[str | None, Query(max_length=128)] = None,
) -> RedirectResponse:
    attempt = await attempt_store(request).consume(
        state,
        request.cookies.get(browser_cookie(request), ""),
        provider,
    )
    correlation_id = getattr(request.state, "request_id", str(uuid4()))
    try:
        adapter = provider_registry(request).get(provider)
        if error is not None or not code or adapter is None:
            raise ExternalLoginFailedError()
        actor = None
        if attempt.intent != "login":
            actor = await sessions.resolve(
                uow,
                request.cookies.get(cookie_name(app_settings(request))),
            )
        identity = await adapter.exchange(code, attempt)
        secret = await finish(
            uow,
            sessions,
            identity=identity,
            attempt=attempt,
            actor=actor,
            correlation_id=correlation_id,
        )
    except (AuthenticationRequiredError, ExternalLoginFailedError) as exc:
        await record_failed_handshake(
            uow,
            attempt=attempt,
            correlation_id=correlation_id,
        )
        if isinstance(exc, ExternalLoginFailedError):
            raise
        raise ExternalLoginFailedError() from None
    response = RedirectResponse(attempt.return_path, status_code=status.HTTP_303_SEE_OTHER)
    response.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    response.delete_cookie(
        browser_cookie(request),
        secure=app_settings(request).secure_cookies,
        httponly=True,
        samesite="lax",
        path="/",
    )
    if secret is not None:
        set_session_cookie(
            response,
            secret,
            app_settings(request),
            sessions.settings.session_seconds,
        )
    return response


@router.get(
    "/identities",
    response_model=list[oidc_schemas.ExternalIdentityView],
    status_code=status.HTTP_200_OK,
)
async def identities(
    actor: CurrentActor,
    uow: Uow,
    response: Response,
) -> list[oidc_schemas.ExternalIdentityView]:
    response.headers["Cache-Control"] = "no-store"
    return await list_identities(uow, actor=actor)


@router.delete("/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_identity(
    provider: ProviderName,
    actor: CurrentActor,
    uow: Uow,
    sessions: Sessions,
    request: Request,
) -> Response:
    await unlink(
        uow,
        sessions,
        actor=actor,
        provider=provider,
        correlation_id=getattr(request.state, "request_id", str(uuid4())),
    )
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={"Cache-Control": "no-store"},
    )
