"""Auth API suite."""

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, Response, status

from ekumidayomi.api.v1.registration import Config
from ekumidayomi.auth import schemas as auth_schemas
from ekumidayomi.auth.challenge_model import PasswordCredential
from ekumidayomi.auth.dependencies import (
    app_settings,
    clear_session_cookie,
    cookie_name,
    current_actor,
    require_origin,
    session_service,
    set_session_cookie,
)
from ekumidayomi.auth.model import AuthSession
from ekumidayomi.auth.passwords import verify_password
from ekumidayomi.auth.service import begin_reset, complete_reset, login
from ekumidayomi.auth.sessions import Actor, SessionService
from ekumidayomi.core.types import utc_now
from ekumidayomi.db.dependencies import get_unit_of_work
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users.errors import AuthenticationRequiredError
from ekumidayomi.users.repository import find_user_by_id

router = APIRouter(prefix="/v1/api/auth", tags=["authentication"])
Uow = Annotated[UnitOfWork, Depends(get_unit_of_work)]
Sessions = Annotated[SessionService, Depends(session_service)]
CurrentActor = Annotated[Actor, Depends(current_actor)]


@router.post(
    "/login", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_origin)]
)
async def sign_in(
    body: auth_schemas.LoginInput, request: Request, uow: Uow, sessions: Sessions
) -> Response:
    secret = await login(uow, sessions, email=body.email, password=body.password.get_secret_value())
    previous = request.cookies.get(cookie_name(app_settings(request)))
    if previous:
        try:
            old_actor = await sessions.resolve(uow, previous)
        except AuthenticationRequiredError:
            old_actor = None
        if old_actor is not None:
            await sessions.revoke(uow, user_id=old_actor.user_id, session_id=old_actor.session_id)
    await uow.commit()
    response = Response(status_code=204)
    set_session_cookie(response, secret, app_settings(request), sessions.settings.session_seconds)
    return response


@router.get("/me")
async def me(actor: CurrentActor, uow: Uow, response: Response) -> dict[str, str]:
    user = await find_user_by_id(uow.session, actor.user_id)
    if user is None:
        raise AuthenticationRequiredError()
    response.headers["Cache-Control"] = "no-store"
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "role": actor.role.value,
    }


@router.post(
    "/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_origin)]
)
async def logout(request: Request, uow: Uow, sessions: Sessions) -> Response:
    try:
        actor = await sessions.resolve(uow, request.cookies.get(cookie_name(app_settings(request))))
    except AuthenticationRequiredError:
        actor = None
    if actor is not None:
        await sessions.revoke(uow, user_id=actor.user_id, session_id=actor.session_id)
        await uow.commit()
    response = Response(status_code=204)
    clear_session_cookie(response, app_settings(request))
    return response


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(
    actor: CurrentActor, request: Request, uow: Uow, sessions: Sessions
) -> Response:
    await find_user_by_id(uow.session, actor.user_id, lock=True)
    await sessions.revoke(uow, user_id=actor.user_id)
    await uow.commit()
    response = Response(status_code=204)
    clear_session_cookie(response, app_settings(request))
    return response


@router.post("/reauthenticate", status_code=status.HTTP_204_NO_CONTENT)
async def reauthenticate(
    body: auth_schemas.PasswordInput, actor: CurrentActor, uow: Uow
) -> Response:
    user = await find_user_by_id(uow.session, actor.user_id, lock=True)
    credential = await uow.session.get(PasswordCredential, actor.user_id)
    valid = await verify_password(
        credential.password_hash if credential else None, body.password.get_secret_value()
    )
    row = await uow.session.get(AuthSession, actor.session_id, populate_existing=True)
    if (
        not valid
        or user is None
        or not user.is_active
        or row is None
        or row.revoked_at is not None
        or row.expires_at <= utc_now()
    ):
        raise AuthenticationRequiredError()
    row.authenticated_at = utc_now()
    await uow.commit()
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.post(
    "/password-reset/request",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=auth_schemas.ChallengeAccepted,
)
async def request_reset(
    body: auth_schemas.EmailInput, uow: Uow, config: Config, response: Response
) -> auth_schemas.ChallengeAccepted:
    identifier = await begin_reset(uow, body.email, config)
    await uow.commit()
    response.headers["Cache-Control"] = "no-store"
    return auth_schemas.ChallengeAccepted(challenge_id=identifier)


@router.post(
    "/password-reset/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_origin)],
)
async def confirm_reset(
    body: auth_schemas.VerifyInput,
    request: Request,
    uow: Uow,
    config: Config,
    sessions: Annotated[SessionService, Depends(session_service)],
) -> Response:
    await complete_reset(
        uow,
        sessions,
        challenge_id=body.challenge_id,
        code=body.code,
        password=body.password.get_secret_value(),
        settings=config,
        correlation_id=getattr(request.state, "request_id", str(uuid4())),
    )
    await uow.commit()
    response = Response(status_code=204)
    clear_session_cookie(response, app_settings(request))
    return response
