import pytest
from pydantic import SecretStr

from ekumidayomi.auth.challenge_model import EmailChallenge
from ekumidayomi.auth.challenges import derive_code
from ekumidayomi.auth.registration import begin_registration, complete_registration
from ekumidayomi.auth.settings import AuthSettings
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users.errors import InvalidChallengeError
from ekumidayomi.users.repository import find_user_by_email


async def test_registration_consumes_challenge_once(identity_uow: UnitOfWork) -> None:
    settings = AuthSettings(challenge_keys={"v1": SecretStr("k" * 32)})
    challenge_id = await begin_registration(identity_uow, "new@example.com", settings)
    await identity_uow.commit()
    row = await identity_uow.session.get(EmailChallenge, challenge_id)
    assert row is not None
    code = derive_code(row, settings)
    assert row.code_hash != code and len(row.code_hash) == 64
    await complete_registration(
        identity_uow,
        challenge_id=challenge_id,
        code=code,
        password="a long enough test password",
        settings=settings,
    )
    await identity_uow.commit()
    user = await find_user_by_email(identity_uow.session, "new@example.com")
    assert user is not None and user.email_verified_at is not None
    with pytest.raises(InvalidChallengeError):
        await complete_registration(
            identity_uow,
            challenge_id=challenge_id,
            code=code,
            password="a different long password",
            settings=settings,
        )
