"""Serialized, purpose-bound email challenges with no plaintext secret storage."""

import hashlib
import hmac
from datetime import timedelta
from uuid import UUID, uuid4

import sqlalchemy as sa

from ekumidayomi.audit.model import ActorKind
from ekumidayomi.audit.service import AuditActor, record_event
from ekumidayomi.auth.challenge_model import ChallengePurpose, EmailChallenge
from ekumidayomi.auth.events import EmailChallengeIssuedEvent, EmailChallengeVerificationFailedEvent
from ekumidayomi.auth.settings import AuthSettings
from ekumidayomi.core.types import utc_now
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.events import DomainEvent
from ekumidayomi.outbox.repository import OutboxRepository
from ekumidayomi.users.errors import EmailVerificationUnavailableError, InvalidChallengeError


async def lock_email(uow: UnitOfWork, email: str) -> None:
    lock_id = int.from_bytes(hashlib.sha256(email.encode()).digest()[:8], signed=True)
    await uow.session.execute(sa.text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})


def key_bytes(settings: AuthSettings, version: str) -> bytes:
    key = settings.challenge_keys.get(version)
    if key is None:
        raise EmailVerificationUnavailableError()
    return key.get_secret_value().encode()


def derive_code(challenge: EmailChallenge, settings: AuthSettings) -> str:
    purpose = ChallengePurpose(challenge.purpose)
    message = f"deliver:{challenge.id}:{purpose.value}".encode()
    digest = hmac.new(key_bytes(settings, challenge.key_version), message, "sha256").digest()
    return f"{int.from_bytes(digest, 'big') % 1000000:06d}"


def code_digest(challenge: EmailChallenge, code: str, settings: AuthSettings) -> str:
    purpose = ChallengePurpose(challenge.purpose)
    message = f"verify:{challenge.id}:{purpose.value}:{code}".encode()
    return hmac.new(key_bytes(settings, challenge.key_version), message, "sha256").hexdigest()


async def issue_challenge(
    uow: UnitOfWork,
    *,
    email: str,
    purpose: str,
    settings: AuthSettings,
    correlation_id: str | None = None,
) -> UUID:
    purpose = ChallengePurpose(purpose)
    key_bytes(settings, settings.active_challenge_key)
    await lock_email(uow, email)
    previous = await uow.session.scalar(
        sa.select(EmailChallenge).where(
            EmailChallenge.email == email, EmailChallenge.purpose == purpose.value
        )
    )
    now = utc_now()
    if previous is not None:
        if (now - previous.created_at).total_seconds() < settings.resend_seconds:
            return uuid4()
        await uow.session.delete(previous)
        await uow.session.flush()
    row = EmailChallenge(
        id=uuid4(),
        email=email,
        purpose=purpose.value,
        key_version=settings.active_challenge_key,
        attempts=0,
        created_at=now,
        expires_at=now + timedelta(seconds=settings.challenge_seconds),
    )
    row.code_hash = code_digest(row, derive_code(row, settings), settings)
    uow.session.add(row)
    OutboxRepository(uow.session).add(
        DomainEvent(
            event_id=uuid4(),
            event_type="email_challenge_requested",
            aggregate_type="email_challenge",
            aggregate_id=row.id,
            aggregate_version=1,
            occurred_at=now,
            payload={"challenge_id": str(row.id)},
        )
    )
    record_event(
        uow,
        EmailChallengeIssuedEvent(
            actor=AuditActor(ActorKind.ANONYMOUS),
            target_id=row.id,
            correlation_id=correlation_id or str(uuid4()),
            purpose=purpose,
            is_resend=previous is not None,
        ),
    )
    await uow.session.flush()
    return row.id


async def consume_challenge(
    uow: UnitOfWork,
    *,
    challenge_id: UUID,
    code: str,
    purpose: ChallengePurpose,
    settings: AuthSettings,
    correlation_id: str | None = None,
) -> EmailChallenge:
    purpose = ChallengePurpose(purpose)
    candidate = await uow.session.get(EmailChallenge, challenge_id)
    if candidate is not None:
        await lock_email(uow, candidate.email)
    row = await uow.session.scalar(
        sa.select(EmailChallenge)
        .where(EmailChallenge.id == challenge_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        row is None
        or row.purpose != purpose.value
        or row.consumed_at is not None
        or row.expires_at <= utc_now()
        or row.attempts >= settings.challenge_attempts
    ):
        record_event(
            uow,
            EmailChallengeVerificationFailedEvent(
                actor=AuditActor(ActorKind.ANONYMOUS),
                target_id=challenge_id,
                correlation_id=correlation_id or str(uuid4()),
                purpose=purpose,
            ),
        )
        await uow.commit()
        raise InvalidChallengeError()
    row.attempts += 1
    if not hmac.compare_digest(row.code_hash, code_digest(row, code, settings)):
        record_event(
            uow,
            EmailChallengeVerificationFailedEvent(
                actor=AuditActor(ActorKind.ANONYMOUS),
                target_id=challenge_id,
                correlation_id=correlation_id or str(uuid4()),
                purpose=purpose,
            ),
        )
        await uow.commit()
        raise InvalidChallengeError()
    row.consumed_at = utc_now()
    return row
