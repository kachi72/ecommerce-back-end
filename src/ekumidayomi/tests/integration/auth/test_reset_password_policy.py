"""Denied password resets do not consume challenges or revoke sessions."""

from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest
from pydantic import SecretStr

from ekumidayomi.auth.challenge_model import EmailChallenge, PasswordCredential
from ekumidayomi.auth.challenges import derive_code
from ekumidayomi.auth.passwords import hash_password
from ekumidayomi.auth.service import begin_reset, complete_reset
from ekumidayomi.auth.sessions import SessionService
from ekumidayomi.auth.settings import AuthSettings
from ekumidayomi.core.types import utc_now
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users.errors import (
    BreachedPasswordError,
    CommonPasswordError,
    PasswordCheckUnavailableError,
)
from ekumidayomi.users.repository import create_customer


@pytest.mark.parametrize("reason", ["common", "breached", "unavailable"])
async def test_policy_failure_preserves_password_challenge_and_session(
    identity_uow: UnitOfWork,
    fake_redis: fakeredis.aioredis.FakeRedis,
    breach_lookup: AsyncMock,
    reason: str,
) -> None:
    config = AuthSettings(challenge_keys={"v1": SecretStr("k" * 32)})
    user = await create_customer(identity_uow.session, email="reset-policy@example.com")
    user.email_verified_at = utc_now()
    original_hash = await hash_password("original meadow passphrase")
    credential = PasswordCredential(user_id=user.id, password_hash=original_hash)
    identity_uow.session.add(credential)
    sessions = SessionService(fake_redis, namespace="test", settings=config)
    secret = await sessions.issue(identity_uow, user)
    await identity_uow.commit()
    identifier = await begin_reset(identity_uow, user.email, config)
    await identity_uow.commit()
    challenge = await identity_uow.session.get(EmailChallenge, identifier)
    assert challenge is not None
    code = derive_code(challenge, config)
    breach_lookup.return_value = reason == "breached"
    if reason == "unavailable":
        breach_lookup.side_effect = PasswordCheckUnavailableError()
    error = {
        "common": CommonPasswordError,
        "breached": BreachedPasswordError,
        "unavailable": PasswordCheckUnavailableError,
    }[reason]
    with pytest.raises(error):
        await complete_reset(
            identity_uow,
            sessions,
            challenge_id=identifier,
            code=code,
            password="a" * 15 if reason == "common" else "quietmeadowsbeyondtheriver",
            settings=config,
            correlation_id="reset-policy-test",
        )
    await identity_uow.commit()
    await identity_uow.session.refresh(challenge)
    await identity_uow.session.refresh(credential)
    assert challenge.consumed_at is None and challenge.attempts == 0
    assert credential.password_hash == original_hash
    assert (await sessions.resolve(identity_uow, secret)).user_id == user.id
    if reason == "common":
        breach_lookup.assert_not_awaited()
    breach_lookup.return_value = False
    breach_lookup.side_effect = None
    await complete_reset(
        identity_uow,
        sessions,
        challenge_id=identifier,
        code=code,
        password="quietmeadowsbeyondtheriver",
        settings=config,
        correlation_id="reset-policy-retry",
    )
    await identity_uow.commit()
    assert credential.password_hash != original_hash
