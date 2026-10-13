"""Challenge failures preserve bounded, purpose-specific identity state."""

from datetime import timedelta

import pytest
from pydantic import SecretStr

from ekumidayomi.auth.challenge_model import ChallengePurpose, EmailChallenge
from ekumidayomi.auth.challenges import consume_challenge, derive_code
from ekumidayomi.auth.registration import begin_registration, complete_registration
from ekumidayomi.auth.settings import AuthSettings
from ekumidayomi.core.types import utc_now
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users.errors import InvalidChallengeError


async def test_wrong_attempts_are_committed_and_exhaust_the_challenge(
    identity_uow: UnitOfWork,
) -> None:
    settings = AuthSettings(challenge_keys={"v1": SecretStr("k" * 32)})
    identifier = await begin_registration(identity_uow, "attempts@example.com", settings)
    challenge = await identity_uow.session.get(EmailChallenge, identifier)
    assert challenge is not None
    correct_code = derive_code(challenge, settings)
    wrong_code = "000000" if correct_code != "000000" else "111111"

    for expected_attempts in range(1, settings.challenge_attempts + 1):
        with pytest.raises(InvalidChallengeError):
            await complete_registration(
                identity_uow,
                challenge_id=identifier,
                code=wrong_code,
                password="quiet meadows beyond the river",
                settings=settings,
            )
        await identity_uow.session.refresh(challenge)
        assert challenge.attempts == expected_attempts

    with pytest.raises(InvalidChallengeError):
        await complete_registration(
            identity_uow,
            challenge_id=identifier,
            code=correct_code,
            password="quiet meadows beyond the river",
            settings=settings,
        )


async def test_expired_and_cross_purpose_challenges_are_rejected(
    identity_uow: UnitOfWork,
) -> None:
    settings = AuthSettings(challenge_keys={"v1": SecretStr("k" * 32)})
    identifier = await begin_registration(identity_uow, "expired@example.com", settings)
    challenge = await identity_uow.session.get(EmailChallenge, identifier)
    assert challenge is not None
    code = derive_code(challenge, settings)

    with pytest.raises(InvalidChallengeError):
        await consume_challenge(
            identity_uow,
            challenge_id=identifier,
            code=code,
            purpose=ChallengePurpose.PASSWORD_RESET,
            settings=settings,
        )

    challenge.expires_at = utc_now() - timedelta(seconds=1)
    await identity_uow.commit()
    with pytest.raises(InvalidChallengeError):
        await consume_challenge(
            identity_uow,
            challenge_id=identifier,
            code=code,
            purpose=ChallengePurpose.REGISTRATION,
            settings=settings,
        )
