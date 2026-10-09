"""Authentication API."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from ekumidayomi.auth import registration as registration_service
from ekumidayomi.auth import schemas as auth_schemas
from ekumidayomi.auth.settings import AuthSettings
from ekumidayomi.core.dependencies import get_auth_settings
from ekumidayomi.db.dependencies import get_unit_of_work
from ekumidayomi.db.uow import UnitOfWork

router = APIRouter(prefix="/v1/api/auth", tags=["authentication"])
Uow = Annotated[UnitOfWork, Depends(get_unit_of_work)]
Config = Annotated[AuthSettings, Depends(get_auth_settings)]


@router.post(
    "/register", status_code=status.HTTP_202_ACCEPTED, response_model=auth_schemas.ChallengeAccepted
)
@router.post(
    "/register/resend",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=auth_schemas.ChallengeAccepted,
)
async def register(
    body: auth_schemas.EmailInput, uow: Uow, config: Config, response: Response, request: Request
) -> auth_schemas.ChallengeAccepted:
    challenge_id = await registration_service.begin_registration(
        uow, body.email, config, correlation_id=request.state.request_id
    )
    await uow.commit()
    response.headers["Cache-Control"] = "no-store"
    return auth_schemas.ChallengeAccepted(challenge_id=challenge_id)


@router.post("/register/verify", status_code=status.HTTP_204_NO_CONTENT)
async def verify(
    body: auth_schemas.VerifyInput, uow: Uow, config: Config, request: Request
) -> Response:
    await registration_service.complete_registration(
        uow,
        challenge_id=body.challenge_id,
        code=body.code,
        password=body.password.get_secret_value(),
        settings=config,
        correlation_id=request.state.request_id,
    )
    await uow.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers={"Cache-Control": "no-store"})
