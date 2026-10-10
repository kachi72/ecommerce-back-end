"""Suite for all services used in auth domain."""

from uuid import UUID, uuid4

from ekumidayomi.audit.model import ActorKind, AuditOutcome
from ekumidayomi.audit.service import AuditActor, record
from ekumidayomi.auth.challenge_model import ChallengePurpose, PasswordCredential
from ekumidayomi.auth.challenges import consume_challenge, issue_challenge
from ekumidayomi.auth.model import AuthSession
from ekumidayomi.auth.password_policy import validate_new_password
from ekumidayomi.auth.passwords import hash_password, needs_rehash, verify_password
from ekumidayomi.auth.sessions import Actor, SessionService
from ekumidayomi.auth.settings import AuthSettings
from ekumidayomi.core.types import utc_now
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users.errors import (
    AuthenticationRequiredError,
    InvalidChallengeError,
    InvalidCredentialsError,
    InvalidEmailError,
)
from ekumidayomi.users.repository import find_user_by_email, find_user_by_id


async def login(
    uow: UnitOfWork,
    sessions: SessionService,
    *,
    email: str,
    password: str,
    previous_secret: str | None = None,
) -> str:
    """Authenticate, replace any valid prior session, and commit atomically."""

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
    secret = await sessions.issue(uow, user)
    if previous_secret is not None:
        try:
            previous_actor = await sessions.resolve(uow, previous_secret)
        except AuthenticationRequiredError:
            previous_actor = None
        if previous_actor is not None:
            await sessions.revoke(
                uow,
                user_id=previous_actor.user_id,
                session_id=previous_actor.session_id,
            )
    await uow.commit()
    return secret


async def logout(uow: UnitOfWork, sessions: SessionService, secret: str | None) -> None:
    """Revoke the presented session when valid; logout remains idempotent."""

    try:
        actor = await sessions.resolve(uow, secret)
    except AuthenticationRequiredError:
        return
    await sessions.revoke(uow, user_id=actor.user_id, session_id=actor.session_id)
    await uow.commit()


async def logout_all(uow: UnitOfWork, sessions: SessionService, actor: Actor) -> None:
    """Revoke every session for the authenticated user and commit."""

    user = await find_user_by_id(uow.session, actor.user_id, lock=True)
    if user is None:
        raise AuthenticationRequiredError()
    await sessions.revoke(uow, user_id=actor.user_id)
    await uow.commit()


async def reauthenticate(uow: UnitOfWork, actor: Actor, *, password: str) -> None:
    """Refresh recent-authentication state after verifying the password."""

    user = await find_user_by_id(uow.session, actor.user_id, lock=True)
    credential = await uow.session.get(PasswordCredential, actor.user_id)
    valid = await verify_password(credential.password_hash if credential else None, password)
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


async def begin_reset(uow: UnitOfWork, email: str, settings: AuthSettings) -> UUID:
    user = await find_user_by_email(uow.session, email)
    if (
        user is None
        or not user.is_active
        or user.email_verified_at is None
        or await uow.session.get(PasswordCredential, user.id) is None
    ):
        challenge_id = uuid4()
    else:
        challenge_id = await issue_challenge(
            uow, email=user.email, purpose=ChallengePurpose.PASSWORD_RESET, settings=settings
        )
    await uow.commit()
    return challenge_id


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
    try:
        challenge = await consume_challenge(
            uow,
            challenge_id=challenge_id,
            code=code,
            purpose=ChallengePurpose.PASSWORD_RESET,
            settings=settings,
        )
    except InvalidChallengeError:
        await uow.commit()
        raise
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
    await uow.commit()
