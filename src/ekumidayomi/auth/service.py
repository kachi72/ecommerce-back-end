"""Suite for all services used in auth domain."""

from uuid import UUID, uuid4

from ekumidayomi.audit.model import ActorKind, AuditOutcome
from ekumidayomi.audit.service import AuditActor, record
from ekumidayomi.auth.challenge_model import ChallengePurpose, PasswordCredential
from ekumidayomi.auth.challenges import consume_challenge, issue_challenge
from ekumidayomi.auth.password_policy import validate_new_password
from ekumidayomi.auth.passwords import hash_password, needs_rehash, verify_password
from ekumidayomi.auth.sessions import SessionService
from ekumidayomi.auth.settings import AuthSettings
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users.errors import (
    AuthenticationRequiredError,
    InvalidCredentialsError,
    InvalidEmailError,
)
from ekumidayomi.users.repository import find_user_by_email, find_user_by_id


async def login(uow: UnitOfWork, sessions: SessionService, *, email: str, password: str) -> str:
    try:
        user = await find_user_by_email(uow.session, email)
    except InvalidEmailError:
        user = None
    if user is not None:
        user = await find_user_by_id(uow.session, user.id, lock=True)
    credential = await uow.session.get(PasswordCredential, user.id) if user is not None else None
    valid = await verify_password(credential.password_hash if credential else None, password)
    if not valid or user is None or not user.is_active or user.email_verified_at is None:
        raise InvalidCredentialsError()
    if credential is not None and needs_rehash(credential.password_hash):
        credential.password_hash = await hash_password(password)
    return await sessions.issue(uow, user)


async def begin_reset(uow: UnitOfWork, email: str, settings: AuthSettings) -> UUID:
    user = await find_user_by_email(uow.session, email)
    if (
        user is None
        or not user.is_active
        or user.email_verified_at is None
        or await uow.session.get(PasswordCredential, user.id) is None
    ):
        return uuid4()
    return await issue_challenge(
        uow, email=user.email, purpose=ChallengePurpose.PASSWORD_RESET, settings=settings
    )


async def complete_reset(
    uow: UnitOfWork,
    sessions: SessionService,
    *,
    challenge_id: UUID,
    code: str,
    password: str,
    settings: AuthSettings,
    correlation_id: str,
) -> None:
    await validate_new_password(password)
    challenge = await consume_challenge(
        uow,
        challenge_id=challenge_id,
        code=code,
        purpose=ChallengePurpose.PASSWORD_RESET,
        settings=settings,
    )
    found = await find_user_by_email(uow.session, challenge.email)
    user = await find_user_by_id(uow.session, found.id, lock=True) if found is not None else None
    if user is None or not user.is_active or user.email_verified_at is None:
        raise AuthenticationRequiredError()
    credential = await uow.session.get(PasswordCredential, user.id, populate_existing=True)
    if credential is None:
        raise AuthenticationRequiredError()
    credential.password_hash = await hash_password(password)
    await sessions.revoke(uow, user_id=user.id)
    record(
        uow,
        actor=AuditActor(ActorKind.ANONYMOUS),
        action="identity.password_reset",
        target_type="user",
        target_id=user.id,
        outcome=AuditOutcome.SUCCEEDED,
        metadata={},
        allowed_metadata_keys=frozenset(),
        correlation_id=correlation_id,
    )
