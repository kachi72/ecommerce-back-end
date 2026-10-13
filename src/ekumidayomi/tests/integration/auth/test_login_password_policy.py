"""Breach-service downtime does not affect existing login or local rehash."""

from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from ekumidayomi.auth import service as auth_service
from ekumidayomi.auth.challenge_model import PasswordCredential
from ekumidayomi.auth.passwords import hash_password, verify_password
from ekumidayomi.auth.sessions import SessionService
from ekumidayomi.auth.settings import AuthSettings
from ekumidayomi.core.types import utc_now
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users.repository import create_customer


async def test_login_rehash_does_not_call_breach_service(
    identity_uow: UnitOfWork,
    fake_redis: fakeredis.aioredis.FakeRedis,
    breach_lookup: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    password = "quiet meadows beyond the river"
    user = await create_customer(identity_uow.session, email="existing-policy@example.com")
    user.email_verified_at = utc_now()
    original_hash = await hash_password(password)
    credential = PasswordCredential(user_id=user.id, password_hash=original_hash)
    identity_uow.session.add(credential)
    await identity_uow.commit()
    sessions = SessionService(fake_redis, namespace="test", settings=AuthSettings())
    monkeypatch.setattr(auth_service, "needs_rehash", lambda encoded: True)
    breach_lookup.side_effect = AssertionError("Login must not call breach screening.")

    secret = await auth_service.login(
        identity_uow,
        sessions,
        email=user.email,
        password=password,
    )

    assert (await sessions.resolve(identity_uow, secret)).user_id == user.id
    assert credential.password_hash != original_hash
    assert await verify_password(credential.password_hash, password)
    breach_lookup.assert_not_awaited()
