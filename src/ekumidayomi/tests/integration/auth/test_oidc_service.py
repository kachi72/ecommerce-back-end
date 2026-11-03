"""OIDC identity resolution is atomic against real PostgreSQL."""

import time
from dataclasses import replace
from typing import cast

import fakeredis.aioredis
import pytest
import sqlalchemy as sa
from redis.asyncio import Redis

from ekumidayomi.audit.model import AuditRecord
from ekumidayomi.auth.challenge_model import PasswordCredential
from ekumidayomi.auth.model import ExternalIdentity
from ekumidayomi.auth.oidc.contracts import Attempt, Identity
from ekumidayomi.auth.oidc.service import finish, unlink
from ekumidayomi.auth.oidc.settings import ProviderName
from ekumidayomi.auth.sessions import SessionService
from ekumidayomi.auth.settings import AuthSettings
from ekumidayomi.core.types import utc_now
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users.errors import ExternalLoginFailedError, FinalLoginMethodError
from ekumidayomi.users.model import Role, User


def login_attempt(provider: ProviderName = ProviderName.GOOGLE) -> Attempt:
    return Attempt(
        provider=provider,
        intent="login",
        browser_hash="browser-hash",
        nonce="nonce",
        verifier="v" * 64,
        redirect_uri="https://api.example.com/callback",
        started_at=int(time.time()),
    )


def verified_identity(
    *,
    provider: ProviderName = ProviderName.GOOGLE,
    subject: str = "provider-subject",
    email: str = "customer@example.com",
) -> Identity:
    return Identity(provider, subject, email, True)


def session_service(fake_redis: fakeredis.aioredis.FakeRedis) -> SessionService:
    return SessionService(
        cast(Redis, fake_redis),
        namespace="test",
        settings=AuthSettings(),
    )


async def test_first_provider_login_creates_customer_identity_and_local_session(
    identity_uow: UnitOfWork,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    sessions = session_service(fake_redis)

    secret = await finish(
        identity_uow,
        sessions,
        identity=verified_identity(),
        attempt=login_attempt(),
        actor=None,
        correlation_id="oidc-first-login",
    )

    assert secret is not None
    actor = await sessions.resolve(identity_uow, secret)
    user = await identity_uow.session.get(User, actor.user_id)
    external = await identity_uow.session.scalar(
        sa.select(ExternalIdentity).where(ExternalIdentity.user_id == actor.user_id)
    )
    actions = set((await identity_uow.session.scalars(sa.select(AuditRecord.action))).all())
    assert user is not None
    assert user.email == "customer@example.com"
    assert user.role == Role.CUSTOMER.value
    assert external is not None
    assert external.provider == ProviderName.GOOGLE.value
    assert external.subject == "provider-subject"
    assert actions == {"identity.provider_linked", "identity.login_succeeded"}


async def test_matching_email_does_not_auto_link(
    identity_uow: UnitOfWork,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    identity_uow.session.add(
        User(
            email="customer@example.com",
            role=Role.CUSTOMER.value,
            is_active=True,
        )
    )
    await identity_uow.commit()

    with pytest.raises(ExternalLoginFailedError):
        await finish(
            identity_uow,
            session_service(fake_redis),
            identity=verified_identity(subject="different-subject"),
            attempt=login_attempt(),
            actor=None,
            correlation_id="oidc-email-collision",
        )

    assert await identity_uow.session.scalar(sa.select(sa.func.count(ExternalIdentity.id))) == 0


async def test_final_provider_login_method_cannot_be_unlinked(
    identity_uow: UnitOfWork,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    sessions = session_service(fake_redis)
    secret = await finish(
        identity_uow,
        sessions,
        identity=verified_identity(),
        attempt=login_attempt(),
        actor=None,
        correlation_id="oidc-final-method-login",
    )
    assert secret is not None
    actor = await sessions.resolve(identity_uow, secret)

    reauthentication = login_attempt().model_copy(
        update={
            "intent": "reauthenticate",
            "actor_id": actor.user_id,
            "session_id": actor.session_id,
        }
    )
    await finish(
        identity_uow,
        sessions,
        identity=replace(verified_identity(), auth_time=int(time.time())),
        attempt=reauthentication,
        actor=actor,
        correlation_id="oidc-provider-reauthentication",
    )
    actor = await sessions.resolve(identity_uow, secret)

    with pytest.raises(FinalLoginMethodError):
        await unlink(
            identity_uow,
            sessions,
            actor=actor,
            provider=ProviderName.GOOGLE,
            correlation_id="oidc-final-method-unlink",
        )


async def test_recent_password_user_can_link_and_unlink_provider(
    identity_uow: UnitOfWork,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    sessions = session_service(fake_redis)
    user = User(
        email="password-user@example.com",
        role=Role.CUSTOMER.value,
        is_active=True,
        email_verified_at=utc_now(),
    )
    identity_uow.session.add(user)
    await identity_uow.session.flush()
    identity_uow.session.add(PasswordCredential(user_id=user.id, password_hash="argon2-hash"))
    secret = await sessions.issue(identity_uow, user)
    await identity_uow.commit()
    actor = await sessions.resolve(identity_uow, secret)
    link_attempt = login_attempt().model_copy(
        update={
            "intent": "link",
            "actor_id": actor.user_id,
            "session_id": actor.session_id,
        }
    )

    result = await finish(
        identity_uow,
        sessions,
        identity=verified_identity(email="password-user@example.com"),
        attempt=link_attempt,
        actor=actor,
        correlation_id="oidc-link",
    )

    assert result is None
    assert (
        await identity_uow.session.scalar(
            sa.select(sa.func.count(ExternalIdentity.id)).where(
                ExternalIdentity.user_id == actor.user_id
            )
        )
        == 1
    )

    await unlink(
        identity_uow,
        sessions,
        actor=actor,
        provider=ProviderName.GOOGLE,
        correlation_id="oidc-unlink",
    )

    assert (
        await identity_uow.session.scalar(
            sa.select(sa.func.count(ExternalIdentity.id)).where(
                ExternalIdentity.user_id == actor.user_id
            )
        )
        == 0
    )
