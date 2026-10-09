import fakeredis.aioredis
import pytest
from pydantic import SecretStr

from ekumidayomi.auth.challenge_model import EmailChallenge, PasswordCredential
from ekumidayomi.auth.challenges import derive_code
from ekumidayomi.auth.passwords import hash_password, verify_password
from ekumidayomi.auth.service import begin_reset, complete_reset
from ekumidayomi.auth.sessions import SessionService
from ekumidayomi.auth.settings import AuthSettings
from ekumidayomi.core.types import utc_now
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users.errors import (
    AuthenticationRequiredError,
    InvalidChallengeError,
)
from ekumidayomi.users.repository import create_customer


async def test_reset_revokes_all_sessions(
    identity_uow: UnitOfWork, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    config = AuthSettings(challenge_keys={"v1": SecretStr("k" * 32)})
    user = await create_customer(identity_uow.session, email="reset@example.com")
    user.email_verified_at = utc_now()
    credential = PasswordCredential(
        user_id=user.id, password_hash=await hash_password("the original long password")
    )
    identity_uow.session.add(credential)
    sessions = SessionService(fake_redis, namespace="test", settings=config)
    first = await sessions.issue(identity_uow, user)
    second = await sessions.issue(identity_uow, user)
    await identity_uow.commit()
    identifier = await begin_reset(identity_uow, user.email, config)
    await identity_uow.commit()
    challenge = await identity_uow.session.get(EmailChallenge, identifier)
    assert challenge is not None
    code = derive_code(challenge, config)
    await complete_reset(
        identity_uow,
        sessions,
        challenge_id=identifier,
        code=code,
        password="the replacement long password",
        settings=config,
        correlation_id="test-reset",
    )
    await identity_uow.commit()
    assert await verify_password(credential.password_hash, "the replacement long password")
    for secret in (first, second):
        with pytest.raises(AuthenticationRequiredError):
            await sessions.resolve(identity_uow, secret)
    with pytest.raises(InvalidChallengeError):
        await complete_reset(
            identity_uow,
            sessions,
            challenge_id=identifier,
            code=code,
            password="the replacement long password",
            settings=config,
            correlation_id="test-reset",
        )
