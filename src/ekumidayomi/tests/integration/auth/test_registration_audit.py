from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa

from ekumidayomi.audit.model import AuditRecord
from ekumidayomi.auth.challenge_model import EmailChallenge, PasswordCredential
from ekumidayomi.auth.challenges import derive_code
from ekumidayomi.auth.registration import begin_registration, complete_registration
from ekumidayomi.auth.settings import AuthSettings
from ekumidayomi.outbox.model import OutboxMessage
from ekumidayomi.users.errors import InvalidChallengeError


def config() -> Any:
    return AuthSettings(challenge_keys={"v1": "x" * 32})


async def test_challenge_audit_outbox_rollback_together(identity_uow: Any) -> None:
    await begin_registration(identity_uow, "rollback@example.com", config())
    await identity_uow.rollback()
    for model in (EmailChallenge, AuditRecord, OutboxMessage):
        assert await identity_uow.session.scalar(sa.select(sa.func.count()).select_from(model)) == 0


async def test_wrong_attempt_and_denial_audit_commit(identity_uow: Any) -> None:
    settings = config()
    challenge_id = await begin_registration(identity_uow, "attempt@example.com", settings)
    await identity_uow.commit()
    row = await identity_uow.session.get(EmailChallenge, challenge_id)
    assert row is not None
    valid = derive_code(row, settings)
    wrong = "000000" if valid != "000000" else "111111"
    with pytest.raises(InvalidChallengeError):
        await complete_registration(
            identity_uow,
            challenge_id=challenge_id,
            code=wrong,
            password="a sufficiently uncommon test phrase",
            settings=settings,
        )
    await identity_uow.rollback()
    row = await identity_uow.session.get(EmailChallenge, challenge_id)
    assert row is not None
    assert row.attempts == 1
    actions = list(await identity_uow.session.scalars(sa.select(AuditRecord.action)))
    assert "auth.challenge_verification_failed" in actions
    assert "auth.registration_completed" not in actions


async def test_registration_completion_audit_is_atomic(identity_uow: Any) -> None:
    settings = config()
    challenge_id = await begin_registration(identity_uow, f"{uuid4().hex}@example.com", settings)
    await identity_uow.commit()
    row = await identity_uow.session.get(EmailChallenge, challenge_id)
    assert row is not None
    await complete_registration(
        identity_uow,
        challenge_id=challenge_id,
        code=derive_code(row, settings),
        password="a sufficiently uncommon test phrase",
        settings=settings,
    )
    await identity_uow.session.flush()
    assert (
        await identity_uow.session.scalar(
            sa.select(sa.func.count())
            .select_from(AuditRecord)
            .where(AuditRecord.action == "auth.registration_completed")
        )
        == 1
    )
    await identity_uow.rollback()
    assert (
        await identity_uow.session.scalar(
            sa.select(sa.func.count()).select_from(PasswordCredential)
        )
        == 0
    )
    assert (
        await identity_uow.session.scalar(
            sa.select(sa.func.count())
            .select_from(AuditRecord)
            .where(AuditRecord.action == "auth.registration_completed")
        )
        == 0
    )
