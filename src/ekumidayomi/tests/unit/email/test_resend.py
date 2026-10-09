import json
from typing import Any
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest

from ekumidayomi.email.resend import ResendEmailSender
from ekumidayomi.email.schemas import OutgoingEmail
from ekumidayomi.email.settings import ResendSettings
from ekumidayomi.outbox.outcomes import OutcomeKind


def settings() -> Any:
    return ResendSettings(
        api_key="test-key",
        sender="notify@example.com",
        fingerprint_key="x" * 32,
    )


def message() -> Any:
    return OutgoingEmail(
        delivery_id=uuid4(),
        recipients=["a@example.com", "b@example.com"],
        subject="Verification",
        text_body="Private code",
    )


async def test_retry_keeps_key_and_body_and_skips_completed_recipient() -> None:
    calls = []
    second_attempt = False

    def endpoint(request: Any) -> Any:
        nonlocal second_attempt
        calls.append((request.headers["Idempotency-Key"], request.content))
        if request.headers["Idempotency-Key"].endswith("/1") and not second_attempt:
            second_attempt = True
            return httpx.Response(
                429,
                json={"name": "rate_limit_exceeded"},
                headers={"Retry-After": "2"},
            )
        return httpx.Response(200, json={"id": str(uuid4())})

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as client:
        sender = ResendEmailSender(settings(), client)
        outgoing = message()
        first = sender.prepare(outgoing)
        outcome = await sender.send(first, {})
        assert outcome.kind is OutcomeKind.RETRY
        assert set(outcome.receipts) == {"0"}
        outgoing.recipients.append("c@example.com")
        result = await sender.send(first, outcome.receipts)
        assert result.kind is OutcomeKind.ACCEPTED
        assert len(calls) == 3
        assert calls[1] == calls[2]
        assert len(json.loads(calls[0][1])["to"]) == 1
        assert "Private code" not in repr(first)


@pytest.mark.parametrize(
    "status,name,kind",
    [
        (401, "missing_api_key", OutcomeKind.BLOCKED),
        (403, "validation_error", OutcomeKind.BLOCKED),
        (409, "invalid_idempotent_request", OutcomeKind.BLOCKED),
        (409, "concurrent_idempotent_requests", OutcomeKind.RETRY),
        (422, "validation_error", OutcomeKind.PERMANENT),
        (429, "daily_quota_exceeded", OutcomeKind.BLOCKED),
        (500, "application_error", OutcomeKind.UNCERTAIN),
        (503, "service_unavailable", OutcomeKind.UNCERTAIN),
    ],
)
async def test_error_classification(status: Any, name: Any, kind: Any) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                status,
                json={"name": name, "message": "private address"},
            )
        )
    ) as client:
        sender = ResendEmailSender(settings(), client)
        outcome = await sender.send(sender.prepare(message()), {})
        assert outcome.kind is kind
        assert "private address" not in repr(outcome)


async def test_timeout_is_uncertain_and_same_key_can_be_retried() -> None:
    keys = []

    def endpoint(request: Any) -> Any:
        keys.append(request.headers["Idempotency-Key"])
        raise httpx.ReadTimeout("private details", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as client:
        sender = ResendEmailSender(settings(), client)
        prepared = sender.prepare(message())
        assert (await sender.send(prepared, {})).kind is OutcomeKind.UNCERTAIN
        assert (await sender.send(prepared, {})).kind is OutcomeKind.UNCERTAIN
        assert keys[0] == keys[1]


async def test_oversized_or_invalid_success_is_not_treated_as_acceptance() -> None:
    for response in (
        httpx.Response(200, text="x" * 16385),
        httpx.Response(200, json={"id": "invalid"}),
    ):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _, response=response: response)
        ) as client:
            sender = ResendEmailSender(settings(), client)
            assert (await sender.send(sender.prepare(message()), {})).kind is OutcomeKind.UNCERTAIN


def test_content_change_changes_fingerprint_not_delivery_key() -> None:
    sender = ResendEmailSender(settings(), Mock(spec=httpx.AsyncClient))
    outgoing = message()
    before = sender.prepare(outgoing)
    after = sender.prepare(outgoing.model_copy(update={"text_body": "Changed code"}))
    assert before.requests[0].key == after.requests[0].key
    assert before.fingerprint != after.fingerprint
