"""Top-level authentication use cases own their transaction boundaries."""

from datetime import timedelta

import fakeredis.aioredis
import pytest

from ekumidayomi.auth import service as auth_service
from ekumidayomi.auth.challenge_model import PasswordCredential
from ekumidayomi.auth.model import AuthSession
from ekumidayomi.auth.passwords import hash_password
from ekumidayomi.auth.sessions import SessionService
from ekumidayomi.auth.settings import AuthSettings
from ekumidayomi.core.types import utc_now
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users.errors import AuthenticationRequiredError
from ekumidayomi.users.repository import create_customer


async def create_verified_user(uow: UnitOfWork, *, email: str, password: str) -> None:
    user = await create_customer(uow.session, email=email)
    user.email_verified_at = utc_now()
    uow.session.add(
        PasswordCredential(user_id=user.id, password_hash=await hash_password(password))
    )
    await uow.commit()


async def test_login_replaces_the_presented_session_and_commits(
    identity_uow: UnitOfWork, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    password = "a sufficiently uncommon login phrase"
    email = "login-transaction@example.com"
    await create_verified_user(identity_uow, email=email, password=password)
    sessions = SessionService(fake_redis, namespace="test", settings=AuthSettings())

    first = await auth_service.login(identity_uow, sessions, email=email, password=password)
    second = await auth_service.login(
        identity_uow,
        sessions,
        email=email,
        password=password,
        previous_secret=first,
    )

    with pytest.raises(AuthenticationRequiredError):
        await sessions.resolve(identity_uow, first)
    assert (await sessions.resolve(identity_uow, second)).user_id is not None


async def test_logout_and_logout_all_commit_revocations(
    identity_uow: UnitOfWork, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    password = "another sufficiently uncommon login phrase"
    email = "logout-transaction@example.com"
    await create_verified_user(identity_uow, email=email, password=password)
    sessions = SessionService(fake_redis, namespace="test", settings=AuthSettings())
    first = await auth_service.login(identity_uow, sessions, email=email, password=password)
    second = await auth_service.login(identity_uow, sessions, email=email, password=password)

    actor = await sessions.resolve(identity_uow, first)
    await auth_service.logout(identity_uow, sessions, first)
    with pytest.raises(AuthenticationRequiredError):
        await sessions.resolve(identity_uow, first)
    assert (await sessions.resolve(identity_uow, second)).user_id == actor.user_id

    second_actor = await sessions.resolve(identity_uow, second)
    third = await auth_service.login(identity_uow, sessions, email=email, password=password)
    await auth_service.logout_all(identity_uow, sessions, second_actor)
    for secret in (second, third):
        with pytest.raises(AuthenticationRequiredError):
            await sessions.resolve(identity_uow, secret)


async def test_reauthenticate_commits_the_refreshed_timestamp(
    identity_uow: UnitOfWork,
    fake_redis: fakeredis.aioredis.FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    password = "a reauthentication phrase that is uncommon"
    email = "reauth-transaction@example.com"
    await create_verified_user(identity_uow, email=email, password=password)
    sessions = SessionService(fake_redis, namespace="test", settings=AuthSettings())
    secret = await auth_service.login(identity_uow, sessions, email=email, password=password)
    actor = await sessions.resolve(identity_uow, secret)
    refreshed_at = actor.authenticated_at + timedelta(seconds=30)
    monkeypatch.setattr(auth_service, "utc_now", lambda: refreshed_at)

    await auth_service.reauthenticate(identity_uow, actor, password=password)

    row = await identity_uow.session.get(AuthSession, actor.session_id, populate_existing=True)
    assert row is not None
    assert row.authenticated_at == refreshed_at
