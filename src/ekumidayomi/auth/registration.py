"""Mailbox verification establishes a password; initiation does not."""

from uuid import UUID, uuid4

from ekumidayomi.audit.model import ActorKind
from ekumidayomi.audit.service import AuditActor, record_event
from ekumidayomi.auth.challenge_model import ChallengePurpose, PasswordCredential
from ekumidayomi.auth.challenges import consume_challenge, issue_challenge, lock_email
from ekumidayomi.auth.events import RegistrationCompletedEvent, RegistrationInitiatedEvent
from ekumidayomi.auth.password_policy import validate_new_password
from ekumidayomi.auth.passwords import hash_password
from ekumidayomi.auth.settings import AuthSettings
from ekumidayomi.core.types import utc_now
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users.errors import InvalidChallengeError
from ekumidayomi.users.repository import create_customer, find_user_by_email, normalize_email


async def begin_registration(
    uow: UnitOfWork, email: str, settings: AuthSettings, *, correlation_id: str | None = None
) -> UUID:
    correlation_id = correlation_id or str(uuid4())
    record_event(
        uow,
        RegistrationInitiatedEvent(
            actor=AuditActor(ActorKind.ANONYMOUS), target_id=uuid4(), correlation_id=correlation_id
        ),
    )
    email = normalize_email(email)
    await lock_email(uow, email)
    user = await find_user_by_email(uow.session, email)
    if user is not None:
        return uuid4()
    return await issue_challenge(
        uow,
        email=email,
        purpose=ChallengePurpose.REGISTRATION,
        settings=settings,
        correlation_id=correlation_id,
    )


async def complete_registration(
    uow: UnitOfWork,
    *,
    challenge_id: UUID,
    code: str,
    password: str,
    settings: AuthSettings,
    correlation_id: str | None = None,
) -> None:
    correlation_id = correlation_id or str(uuid4())
    await validate_new_password(password)
    challenge = await consume_challenge(
        uow,
        challenge_id=challenge_id,
        code=code,
        purpose=ChallengePurpose.REGISTRATION,
        settings=settings,
    )
    if await find_user_by_email(uow.session, challenge.email) is not None:
        raise InvalidChallengeError()
    user = await create_customer(uow.session, email=challenge.email)
    user.email_verified_at = utc_now()
    uow.session.add(
        PasswordCredential(user_id=user.id, password_hash=await hash_password(password))
    )
    record_event(
        uow,
        RegistrationCompletedEvent(
            actor=AuditActor(ActorKind.ANONYMOUS), target_id=user.id, correlation_id=correlation_id
        ),
    )
