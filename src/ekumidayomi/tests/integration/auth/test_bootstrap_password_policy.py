"""Bootstrap uses the customer password policy without changing idempotency."""

from unittest.mock import AsyncMock

import pytest

from ekumidayomi.auth.bootstrap import bootstrap
from ekumidayomi.auth.challenge_model import PasswordCredential
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users.errors import (
    BreachedPasswordError,
    CommonPasswordError,
    PasswordCheckUnavailableError,
)
from ekumidayomi.users.repository import find_user_by_email


@pytest.mark.parametrize("reason", ["common", "breached", "unavailable"])
async def test_new_admin_cannot_bypass_password_policy(
    identity_uow: UnitOfWork, breach_lookup: AsyncMock, reason: str
) -> None:
    breach_lookup.return_value = reason == "breached"
    if reason == "unavailable":
        breach_lookup.side_effect = PasswordCheckUnavailableError()
    error = {
        "common": CommonPasswordError,
        "breached": BreachedPasswordError,
        "unavailable": PasswordCheckUnavailableError,
    }[reason]
    with pytest.raises(error):
        await bootstrap(
            identity_uow,
            email="policy-admin@example.com",
            password="a" * 15 if reason == "common" else "quietmeadowsbeyondtheriver",
        )
    await identity_uow.commit()
    assert await find_user_by_email(identity_uow.session, "policy-admin@example.com") is None
    if reason == "common":
        breach_lookup.assert_not_awaited()


async def test_existing_admin_rerun_does_not_check_or_replace_password(
    identity_uow: UnitOfWork, breach_lookup: AsyncMock
) -> None:
    await bootstrap(
        identity_uow, email="policy-admin@example.com", password="quietmeadowsbeyondtheriver"
    )
    await identity_uow.commit()
    user = await find_user_by_email(identity_uow.session, "policy-admin@example.com")
    assert user is not None
    credential = await identity_uow.session.get(PasswordCredential, user.id)
    assert credential is not None
    original_hash = credential.password_hash
    breach_lookup.reset_mock()
    breach_lookup.side_effect = AssertionError("An existing admin needs no password screening.")
    await bootstrap(identity_uow, email=user.email, password="unused")
    await identity_uow.commit()
    assert credential.password_hash == original_hash
    breach_lookup.assert_not_awaited()
