from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from ekumidayomi.auth.email_handler import AuthChallengeEmailHandler
from ekumidayomi.auth.settings import AuthSettings
from ekumidayomi.core.types import utc_now
from ekumidayomi.events import DomainEvent
from ekumidayomi.outbox.leased_repository import LeasedOutboxRepository
from ekumidayomi.outbox.outcomes import DeliveryOutcome, OutcomeKind


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
