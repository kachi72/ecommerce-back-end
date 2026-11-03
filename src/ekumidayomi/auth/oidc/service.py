"""Map verified external subjects to durable local users and sessions."""

from datetime import timedelta

import sqlalchemy as sa

from ekumidayomi.audit.model import ActorKind
from ekumidayomi.audit.service import AuditActor, record_event
from ekumidayomi.auth.challenge_model import PasswordCredential
from ekumidayomi.auth.challenges import lock_email
from ekumidayomi.auth.events import (
    ExternalIdentityLinkedEvent,
    ExternalIdentityUnlinkedEvent,
    ExternalLoginFailedEvent,
    ExternalLoginSucceededEvent,
    ExternalReauthenticationSucceededEvent,
)
from ekumidayomi.auth.model import AuthSession, ExternalIdentity
from ekumidayomi.auth.oidc.contracts import Attempt, Identity
from ekumidayomi.auth.oidc.schemas import ExternalIdentityView
from ekumidayomi.auth.oidc.settings import ProviderName
from ekumidayomi.auth.permissions import Permission, authorize
from ekumidayomi.auth.sessions import Actor, SessionService, digest
from ekumidayomi.core.types import utc_now
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users.errors import (
    ExternalLoginFailedError,
    FinalLoginMethodError,
    InvalidEmailError,
    ProviderAlreadyLinkedError,
)
from ekumidayomi.users.model import Role, User
from ekumidayomi.users.repository import (
    create_customer,
    find_user_by_email,
    find_user_by_id,
    normalize_email,
)


def _audit_actor(user: User) -> AuditActor:
    try:
        role = Role(user.role)
    except ValueError:
        raise ExternalLoginFailedError() from None
    kind = ActorKind.ADMINISTRATOR if role == Role.ADMIN else ActorKind.CUSTOMER
    return AuditActor(kind, user.id)


def _actor_from_session(actor: Actor) -> AuditActor:
    kind = ActorKind.ADMINISTRATOR if actor.role == Role.ADMIN else ActorKind.CUSTOMER
    return AuditActor(kind, actor.user_id)


async def record_failed_handshake(
    uow: UnitOfWork,
    *,
    attempt: Attempt,
    correlation_id: str,
) -> None:
    """Persist bounded denial evidence after discarding pending business state."""

    await uow.rollback()
    record_event(
        uow,
        ExternalLoginFailedEvent(
            actor=AuditActor(ActorKind.ANONYMOUS),
            target_id=attempt.attempt_id,
            correlation_id=correlation_id,
            provider=attempt.provider.value,
            intent=attempt.intent,
        ),
    )
    await uow.commit()


async def finish(
    uow: UnitOfWork,
    sessions: SessionService,
    *,
    identity: Identity,
    attempt: Attempt,
    actor: Actor | None,
    correlation_id: str,
) -> str | None:
    """Complete login, link, or reauthentication and own the commit boundary."""

    if identity.provider != attempt.provider:
        raise ExternalLoginFailedError()
    await lock_email(uow, f"external:{identity.provider.value}:{identity.subject}")
    external = await uow.session.scalar(
        sa.select(ExternalIdentity).where(
            ExternalIdentity.provider == identity.provider.value,
            ExternalIdentity.subject == identity.subject,
        )
    )

    if attempt.intent != "login":
        if (
            actor is None
            or actor.user_id != attempt.actor_id
            or actor.session_id != attempt.session_id
        ):
            raise ExternalLoginFailedError()
        user = await authorize(
            uow,
            actor,
            Permission.PROFILE_WRITE,
            lock=True,
            recent_seconds=(
                sessions.settings.recent_auth_seconds if attempt.intent == "link" else None
            ),
        )
        if attempt.intent == "reauthenticate":
            if external is None or external.user_id != actor.user_id or identity.auth_time is None:
                raise ExternalLoginFailedError()
            session = await uow.session.get(AuthSession, actor.session_id, populate_existing=True)
            if session is None or session.revoked_at is not None or session.expires_at <= utc_now():
                raise ExternalLoginFailedError()
            session.authenticated_at = utc_now()
            external.last_login_at = utc_now()
            record_event(
                uow,
                ExternalReauthenticationSucceededEvent(
                    actor=_actor_from_session(actor),
                    target_id=user.id,
                    correlation_id=correlation_id,
                    provider=identity.provider.value,
                ),
            )
            await uow.commit()
            return None
        if external is not None:
            if external.user_id == user.id:
                raise ProviderAlreadyLinkedError()
            raise ExternalLoginFailedError()
        already = await uow.session.scalar(
            sa.select(ExternalIdentity.id).where(
                ExternalIdentity.user_id == user.id,
                ExternalIdentity.provider == identity.provider.value,
            )
        )
        if already is not None:
            raise ProviderAlreadyLinkedError()
    elif external is not None:
        resolved_user = await find_user_by_id(uow.session, external.user_id, lock=True)
        if (
            resolved_user is None
            or not resolved_user.is_active
            or resolved_user.email_verified_at is None
        ):
            raise ExternalLoginFailedError()
        user = resolved_user
    else:
        if not identity.email or not identity.email_verified:
            raise ExternalLoginFailedError()
        try:
            email = normalize_email(identity.email)
        except InvalidEmailError:
            raise ExternalLoginFailedError() from None
        await lock_email(uow, email)
        if await find_user_by_email(uow.session, email) is not None:
            # Email equality is not proof that the account owner consented to linking.
            raise ExternalLoginFailedError()
        user = await create_customer(uow.session, email=email)
        user.email_verified_at = utc_now()

    if external is None:
        external = ExternalIdentity(
            user_id=user.id,
            provider=identity.provider.value,
            subject=identity.subject,
            email_snapshot=identity.email[:320] if identity.email else None,
            email_verified=identity.email_verified,
            last_login_at=utc_now(),
        )
        uow.session.add(external)
        record_event(
            uow,
            ExternalIdentityLinkedEvent(
                actor=_audit_actor(user),
                target_id=user.id,
                correlation_id=correlation_id,
                provider=identity.provider.value,
            ),
        )
    else:
        external.last_login_at = utc_now()
    await uow.session.flush()

    if attempt.intent == "login":
        secret = await sessions.issue(uow, user)
        session = await uow.session.scalar(
            sa.select(AuthSession).where(AuthSession.secret_hash == digest(secret))
        )
        if session is None:
            raise ExternalLoginFailedError()
        # Passive provider SSO is not recent explicit reauthentication.
        session.authenticated_at = utc_now() - timedelta(
            seconds=sessions.settings.recent_auth_seconds + 1
        )
        record_event(
            uow,
            ExternalLoginSucceededEvent(
                actor=_audit_actor(user),
                target_id=user.id,
                correlation_id=correlation_id,
                provider=identity.provider.value,
            ),
        )
        await uow.commit()
        return secret

    await uow.commit()
    return None


async def list_identities(
    uow: UnitOfWork,
    *,
    actor: Actor,
) -> list[ExternalIdentityView]:
    """Return provider names only; subjects and claim snapshots remain private."""

    await authorize(uow, actor, Permission.PROFILE_WRITE)
    providers = (
        await uow.session.scalars(
            sa.select(ExternalIdentity.provider)
            .where(ExternalIdentity.user_id == actor.user_id)
            .order_by(ExternalIdentity.provider)
        )
    ).all()
    return [ExternalIdentityView(provider=ProviderName(provider)) for provider in providers]


async def unlink(
    uow: UnitOfWork,
    sessions: SessionService,
    *,
    actor: Actor,
    provider: ProviderName,
    correlation_id: str,
) -> None:
    """Remove a provider only after recent auth and final-method protection."""

    existing = await uow.session.scalar(
        sa.select(ExternalIdentity).where(
            ExternalIdentity.user_id == actor.user_id,
            ExternalIdentity.provider == provider.value,
        )
    )
    if existing is None:
        raise ExternalLoginFailedError()
    await lock_email(uow, f"external:{existing.provider}:{existing.subject}")
    await authorize(
        uow,
        actor,
        Permission.PROFILE_WRITE,
        lock=True,
        recent_seconds=sessions.settings.recent_auth_seconds,
    )
    existing = await uow.session.scalar(
        sa.select(ExternalIdentity)
        .where(
            ExternalIdentity.user_id == actor.user_id,
            ExternalIdentity.provider == provider.value,
        )
        .execution_options(populate_existing=True)
    )
    if existing is None:
        raise ExternalLoginFailedError()
    identity_count = int(
        await uow.session.scalar(
            sa.select(sa.func.count())
            .select_from(ExternalIdentity)
            .where(ExternalIdentity.user_id == actor.user_id)
        )
        or 0
    )
    password = await uow.session.get(PasswordCredential, actor.user_id)
    if identity_count <= 1 and password is None:
        raise FinalLoginMethodError()
    await uow.session.delete(existing)
    record_event(
        uow,
        ExternalIdentityUnlinkedEvent(
            actor=_actor_from_session(actor),
            target_id=actor.user_id,
            correlation_id=correlation_id,
            provider=provider.value,
        ),
    )
    await uow.commit()
