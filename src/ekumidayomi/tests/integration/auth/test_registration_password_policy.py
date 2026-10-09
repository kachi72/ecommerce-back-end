"""Denied new passwords leave registration state unchanged."""

from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

from ekumidayomi.auth.challenge_model import EmailChallenge
from ekumidayomi.auth.challenges import derive_code
from ekumidayomi.auth.registration import begin_registration, complete_registration
from ekumidayomi.auth.settings import AuthSettings
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users.errors import (
    BreachedPasswordError,
    CommonPasswordError,
    PasswordCheckUnavailableError,
)
from ekumidayomi.users.repository import find_user_by_email


@pytest.mark.parametrize("reason", ["common", "breached", "unavailable"])
async def test_policy_failure_does_not_consume_registration(
    identity_uow: UnitOfWork, breach_lookup: AsyncMock, reason: str
) -> None:
    config = AuthSettings(challenge_keys={"v1": SecretStr("k" * 32)})
    identifier = await begin_registration(identity_uow, "policy@example.com", config)
    await identity_uow.commit()
    row = await identity_uow.session.get(EmailChallenge, identifier)
    assert row is not None
    code = derive_code(row, config)
    breach_lookup.return_value = reason == "breached"
    if reason == "unavailable":
        breach_lookup.side_effect = PasswordCheckUnavailableError()
    error = {
        "common": CommonPasswordError,
        "breached": BreachedPasswordError,
        "unavailable": PasswordCheckUnavailableError,
    }[reason]
    with pytest.raises(error):
        await complete_registration(
            identity_uow,
            challenge_id=identifier,
            code=code,
            password="a" * 15 if reason == "common" else "quietmeadowsbeyondtheriver",
            settings=config,
        )
    await identity_uow.commit()
    await identity_uow.session.refresh(row)
    assert row.consumed_at is None and row.attempts == 0
    assert await find_user_by_email(identity_uow.session, "policy@example.com") is None
    if reason == "common":
        breach_lookup.assert_not_awaited()
    breach_lookup.side_effect = None
    breach_lookup.return_value = False
    await complete_registration(
        identity_uow,
        challenge_id=identifier,
        code=code,
        password="quietmeadowsbeyondtheriver",
        settings=config,
    )
    await identity_uow.commit()
    assert await find_user_by_email(identity_uow.session, "policy@example.com") is not None
