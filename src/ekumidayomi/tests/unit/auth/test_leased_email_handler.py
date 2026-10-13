from datetime import timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from pydantic import SecretStr

from ekumidayomi.auth.challenge_model import ChallengePurpose, EmailChallenge
from ekumidayomi.auth.email_handler import AuthChallengeEmailHandler
from ekumidayomi.auth.settings import AuthSettings
from ekumidayomi.core.types import utc_now
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.email.ports import EmailRequest, EmailSender, EmailSubmission
from ekumidayomi.events import DomainEvent
from ekumidayomi.outbox.leased_repository import LeasedOutboxRepository
from ekumidayomi.outbox.outcomes import DeliveryOutcome, OutcomeKind
from ekumidayomi.outbox.ports import PreparedDelivery


@pytest.mark.parametrize("state", ["missing", "expired", "consumed"])
async def test_ineligible_challenge_never_prepares_or_sends(
    state: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = utc_now()
    challenge_id = uuid4()
    row = (
        None
        if state == "missing"
        else SimpleNamespace(
            consumed_at=now if state == "consumed" else None,
            expires_at=now - timedelta(seconds=1)
            if state == "expired"
            else now + timedelta(seconds=30),
        )
    )
    monkeypatch.setattr(LeasedOutboxRepository, "now", AsyncMock(return_value=now))
    sender = Mock()
    handler = AuthChallengeEmailHandler(sender, AuthSettings())
    event = DomainEvent(
        uuid4(),
        "email_challenge_requested",
        "email_challenge",
        challenge_id,
        1,
        now,
        {"challenge_id": str(challenge_id)},
    )
    result = await handler.prepare(
        SimpleNamespace(session=SimpleNamespace(get=AsyncMock(return_value=row))),
        event,
    )
    assert isinstance(result, DeliveryOutcome)
    assert result.kind is OutcomeKind.SKIPPED
    sender.prepare.assert_not_called()
    sender.send.assert_not_called()


async def test_bad_event_is_permanent_without_database_lookup() -> None:
    sender = Mock()
    handler = AuthChallengeEmailHandler(sender, AuthSettings())
    uow = SimpleNamespace(session=SimpleNamespace(get=AsyncMock()))
    event = DomainEvent(
        uuid4(),
        "email_challenge_requested",
        "email_challenge",
        uuid4(),
        1,
        utc_now(),
        {},
    )
    result = await handler.prepare(uow, event)
    assert isinstance(result, DeliveryOutcome)
    assert result.kind is OutcomeKind.PERMANENT
    uow.session.get.assert_not_awaited()


def challenge_event(challenge: EmailChallenge) -> DomainEvent:
    return DomainEvent(
        uuid4(),
        "email_challenge_requested",
        "email_challenge",
        challenge.id,
        1,
        utc_now(),
        {"challenge_id": str(challenge.id)},
    )


@pytest.mark.parametrize(
    ("purpose", "subject"),
    [
        (ChallengePurpose.REGISTRATION, "Ẹkúmidáyọ̀mí verification code"),
        (ChallengePurpose.PASSWORD_RESET, "Ẹkúmidáyọ̀mí password reset code"),
    ],
)
async def test_valid_challenge_prepares_and_delivers_provider_content(
    monkeypatch: pytest.MonkeyPatch,
    purpose: ChallengePurpose,
    subject: str,
) -> None:
    now = utc_now()
    settings = AuthSettings(challenge_keys={"v1": SecretStr("k" * 32)})
    challenge = EmailChallenge(
        id=uuid4(),
        email="customer@example.com",
        purpose=purpose.value,
        key_version="v1",
        code_hash="hash",
        attempts=0,
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    submission = EmailSubmission(
        requests=(EmailRequest("recipient-key", b"private-body"),),
        fingerprint="fingerprint",
    )
    sender = Mock()
    sender.prepare.return_value = submission
    sender.send = AsyncMock(return_value=DeliveryOutcome(OutcomeKind.ACCEPTED, "provider_accepted"))
    monkeypatch.setattr(LeasedOutboxRepository, "now", AsyncMock(return_value=now))
    uow = SimpleNamespace(session=SimpleNamespace(get=AsyncMock(return_value=challenge)))
    handler = AuthChallengeEmailHandler(cast(EmailSender, sender), settings)

    prepared = await handler.prepare(cast(UnitOfWork, uow), challenge_event(challenge))

    assert isinstance(prepared, PreparedDelivery)
    assert prepared.fingerprint == "fingerprint"
    assert prepared.expires_at == challenge.expires_at
    outgoing = sender.prepare.call_args.args[0]
    assert outgoing.recipients == ["customer@example.com"]
    assert outgoing.subject == subject
    assert "code is" in outgoing.text_body
    outcome = await handler.deliver(prepared, {"recipient-key": "provider-id"})
    assert outcome.kind is OutcomeKind.ACCEPTED
    sender.send.assert_awaited_once_with(
        submission,
        {"recipient-key": "provider-id"},
    )


@pytest.mark.parametrize(
    ("purpose", "key_version", "expected_kind", "expected_code"),
    [
        ("unsupported", "v1", OutcomeKind.PERMANENT, "invalid_challenge_purpose"),
        (
            ChallengePurpose.REGISTRATION.value,
            "missing",
            OutcomeKind.BLOCKED,
            "challenge_key_missing",
        ),
    ],
)
async def test_invalid_purpose_and_missing_key_do_not_prepare(
    monkeypatch: pytest.MonkeyPatch,
    purpose: str,
    key_version: str,
    expected_kind: OutcomeKind,
    expected_code: str,
) -> None:
    now = utc_now()
    challenge = EmailChallenge(
        id=uuid4(),
        email="customer@example.com",
        purpose=purpose,
        key_version=key_version,
        code_hash="hash",
        attempts=0,
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    sender = Mock()
    settings = AuthSettings(challenge_keys={"v1": SecretStr("k" * 32)})
    monkeypatch.setattr(LeasedOutboxRepository, "now", AsyncMock(return_value=now))
    result = await AuthChallengeEmailHandler(sender, settings).prepare(
        SimpleNamespace(session=SimpleNamespace(get=AsyncMock(return_value=challenge))),
        challenge_event(challenge),
    )

    assert isinstance(result, DeliveryOutcome)
    assert (result.kind, result.code) == (expected_kind, expected_code)
    sender.prepare.assert_not_called()


async def test_deliver_rejects_non_email_payload() -> None:
    sender = Mock(send=AsyncMock())
    handler = AuthChallengeEmailHandler(sender, AuthSettings())
    result = await handler.deliver(
        PreparedDelivery(object(), "fingerprint", utc_now()),
        {},
    )
    assert (result.kind, result.code) == (
        OutcomeKind.PERMANENT,
        "invalid_prepared_delivery",
    )
    sender.send.assert_not_awaited()
