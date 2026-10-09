"""Typed evidence and the shared recorder retain the audit safety boundary."""

import inspect
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import Mock, call
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ekumidayomi.audit import events, service
from ekumidayomi.audit.events import AuditData, AuditEvent, BaseAuditEvent
from ekumidayomi.audit.model import ActorKind, AuditOutcome, AuditRecord
from ekumidayomi.audit.service import REDACTED_VALUE, AuditActor, record_event
from ekumidayomi.auth.challenge_model import ChallengePurpose
from ekumidayomi.auth.events import (
    EmailChallengeIssuedEvent,
    EmailChallengeVerificationFailedEvent,
    RegistrationCompletedEvent,
    RegistrationInitiatedEvent,
)
from ekumidayomi.db.uow import UnitOfWork


class SnapshotEvent:
    """Structural protocol implementation; no inheritance is necessary."""

    def __init__(self, data: AuditData) -> None:
        self.data = data
        self.calls = 0

    def to_record(self) -> AuditData:
        self.calls += 1
        return self.data


@pytest.fixture
def evidence() -> AuditData:
    return AuditData(
        actor=AuditActor(ActorKind.CUSTOMER, actor_id=uuid4()),
        action="auth.registration_completed",
        target_type="user",
        target_id=uuid4(),
        outcome=AuditOutcome.SUCCEEDED,
        metadata={"purpose": "registration"},
        allowed_metadata_keys=frozenset({"purpose"}),
        correlation_id="request-1",
        occurred_at=datetime(2026, 9, 15, 12, tzinfo=UTC),
    )


@pytest.fixture
def uow_spy() -> Mock:
    uow = Mock(spec=UnitOfWork)
    uow.session = Mock(spec=AsyncSession)
    return uow


@pytest.mark.parametrize(
    "event_type, action, target_type",
    [
        (RegistrationInitiatedEvent, "auth.registration_requested", "registration_attempt"),
        (RegistrationCompletedEvent, "auth.registration_completed", "user"),
    ],
)
def test_registration_events_use_shared_recorder(
    event_type: type[RegistrationInitiatedEvent] | type[RegistrationCompletedEvent],
    action: str,
    target_type: str,
    evidence: AuditData,
    uow_spy: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(events, "utc_now", lambda: evidence.occurred_at)
    event = event_type(
        actor=evidence.actor, target_id=evidence.target_id, correlation_id=evidence.correlation_id
    )
    row = record_event(cast(UnitOfWork, uow_spy), event)
    assert row.action == action
    assert row.target_type == target_type
    assert row.outcome == AuditOutcome.SUCCEEDED.value
    assert row.actor_kind == evidence.actor.kind.value
    assert row.actor_id == evidence.actor.actor_id
    assert row.target_id == evidence.target_id
    assert row.correlation_id == evidence.correlation_id
    assert row.occurred_at == evidence.occurred_at
    assert row.metadata_ == {}
    uow_spy.session.add.assert_called_once_with(row)


@pytest.mark.parametrize("purpose", list(ChallengePurpose))
@pytest.mark.parametrize("is_resend", [False, True])
def test_challenge_issued_event_records_only_declared_metadata(
    purpose: ChallengePurpose, is_resend: bool, uow_spy: Mock
) -> None:
    event = EmailChallengeIssuedEvent(
        actor=AuditActor(ActorKind.ANONYMOUS),
        target_id=uuid4(),
        correlation_id="request-1",
        purpose=purpose,
        is_resend=is_resend,
    )
    data = event.to_record()
    assert data.action == "auth.challenge_issued"
    assert data.target_type == "email_challenge"
    assert data.outcome is AuditOutcome.SUCCEEDED
    assert data.metadata == {"purpose": purpose.value, "is_resend": is_resend}
    assert data.allowed_metadata_keys == frozenset(data.metadata)
    row = record_event(cast(UnitOfWork, uow_spy), event)
    assert row.metadata_ == dict(data.metadata)
    assert row.actor_kind == "anonymous" and row.actor_id is None


@pytest.mark.parametrize("purpose", list(ChallengePurpose))
def test_failed_verification_is_denied_with_only_purpose(
    purpose: ChallengePurpose, uow_spy: Mock
) -> None:
    event = EmailChallengeVerificationFailedEvent(
        actor=AuditActor(ActorKind.ANONYMOUS),
        target_id=uuid4(),
        correlation_id="request-1",
        purpose=purpose,
    )
    data = event.to_record()
    assert data.action == "auth.challenge_verification_failed"
    assert data.target_type == "email_challenge"
    assert data.outcome is AuditOutcome.DENIED
    assert data.metadata == {"purpose": purpose.value}
    assert data.allowed_metadata_keys == frozenset({"purpose"})
    row = record_event(cast(UnitOfWork, uow_spy), event)
    assert row.outcome == "denied" and row.metadata_ == dict(data.metadata)


def test_resend_defaults_to_false_and_metadata_is_fresh() -> None:
    event = EmailChallengeIssuedEvent(
        actor=AuditActor(ActorKind.ANONYMOUS),
        target_id=uuid4(),
        correlation_id="request-1",
        purpose=ChallengePurpose.REGISTRATION,
    )
    first = event.metadata
    assert isinstance(first, dict)
    first["password"] = "never persist this"
    first["is_resend"] = True
    assert event.metadata == {"purpose": "registration", "is_resend": False}
    assert event.allowed_metadata_keys == frozenset({"purpose", "is_resend"})


@pytest.mark.parametrize(
    "event_type", [EmailChallengeIssuedEvent, EmailChallengeVerificationFailedEvent]
)
def test_invalid_purpose_is_rejected_before_staging(
    event_type: type[EmailChallengeIssuedEvent] | type[EmailChallengeVerificationFailedEvent],
    uow_spy: Mock,
) -> None:
    event = event_type(
        actor=AuditActor(ActorKind.ANONYMOUS),
        target_id=uuid4(),
        correlation_id="request-1",
        purpose=cast(ChallengePurpose, "unsupported"),
    )
    with pytest.raises(ValueError):
        record_event(cast(UnitOfWork, uow_spy), event)
    assert uow_spy.mock_calls == []


def test_base_event_requires_metadata_implementation() -> None:
    class MissingMetadata(BaseAuditEvent):
        action = "auth.test"
        target_type = "user"

    assert inspect.isabstract(BaseAuditEvent)
    assert inspect.isabstract(MissingMetadata)
    assert MissingMetadata.__abstractmethods__ == frozenset({"metadata"})


@pytest.mark.parametrize("field_name", ["correlation_id", "target_id"])
def test_data_and_event_fields_are_frozen(evidence: AuditData, field_name: str) -> None:
    event = RegistrationCompletedEvent(
        actor=evidence.actor, target_id=evidence.target_id, correlation_id=evidence.correlation_id
    )
    for value in (event, evidence):
        with pytest.raises(FrozenInstanceError):
            setattr(value, field_name, "changed")
    # Frozen fields do not imply deeply immutable arbitrary Mapping contents.


def test_timestamp_is_utc_and_created_when_converting(monkeypatch: pytest.MonkeyPatch) -> None:
    first = datetime(2026, 9, 15, 12, tzinfo=UTC)
    second = datetime(2026, 9, 15, 13, tzinfo=UTC)
    clock = Mock(side_effect=[first, second])
    monkeypatch.setattr(events, "utc_now", clock)
    event = RegistrationInitiatedEvent(
        actor=AuditActor(ActorKind.SYSTEM), target_id=uuid4(), correlation_id="request-1"
    )
    clock.assert_not_called()
    assert event.to_record().occurred_at == first
    assert event.to_record().occurred_at == second
    assert clock.call_count == 2


def test_structural_event_forwards_every_field_once(
    evidence: AuditData, uow_spy: Mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    event = SnapshotEvent(evidence)
    contract: AuditEvent = event
    expected = AuditRecord()
    recorder = Mock(return_value=expected)
    monkeypatch.setattr(service, "record", recorder)
    uow = cast(UnitOfWork, uow_spy)
    assert record_event(uow, contract) is expected
    assert event.calls == 1
    recorder.assert_called_once_with(
        uow,
        actor=evidence.actor,
        action=evidence.action,
        target_type=evidence.target_type,
        target_id=evidence.target_id,
        outcome=evidence.outcome,
        metadata=evidence.metadata,
        allowed_metadata_keys=evidence.allowed_metadata_keys,
        correlation_id=evidence.correlation_id,
        occurred_at=evidence.occurred_at,
    )


def test_recorder_only_stages_audit_and_leaves_transaction_to_caller(
    evidence: AuditData, uow_spy: Mock
) -> None:
    event = SnapshotEvent(evidence)
    row = record_event(cast(UnitOfWork, uow_spy), event)
    assert isinstance(row, AuditRecord)
    assert event.calls == 1
    # No flush, commit, rollback, callback, outbox write or other session operation.
    assert uow_spy.mock_calls == [call.session.add(row)]


def test_recorder_still_sanitizes_and_does_not_mutate_event_metadata(
    evidence: AuditData, uow_spy: Mock
) -> None:
    metadata: dict[str, object] = {
        "purpose": "registration",
        "password": "secret-value",
        "ignored": "not-allowlisted",
        "nested": {"purpose": "registration", "otp": "123456"},
    }
    event = SnapshotEvent(
        replace(
            evidence,
            metadata=metadata,
            allowed_metadata_keys=frozenset({"purpose", "password", "nested", "otp"}),
        )
    )
    row = record_event(cast(UnitOfWork, uow_spy), event)
    assert row.metadata_ == {
        "purpose": "registration",
        "password": REDACTED_VALUE,
        "nested": {"purpose": "registration", "otp": REDACTED_VALUE},
    }
    assert metadata["password"] == "secret-value"
    assert metadata["nested"] == {"purpose": "registration", "otp": "123456"}
    metadata["purpose"] = "changed-after-recording"
    assert row.metadata_["purpose"] == "registration"


@pytest.mark.parametrize(
    "changes, error_type",
    [
        ({"action": "INVALID ACTION"}, ValueError),
        ({"target_type": ""}, ValueError),
        ({"target_id": "not-a-uuid"}, TypeError),
        ({"outcome": "unknown"}, ValueError),
        ({"correlation_id": "unsafe\nvalue"}, ValueError),
        ({"occurred_at": datetime(2026, 9, 15)}, ValueError),
        ({"allowed_metadata_keys": frozenset({"Bad Key"})}, ValueError),
        ({"metadata": {"purpose": object()}}, TypeError),
        ({"metadata": {"purpose": float("nan")}}, ValueError),
        ({"metadata": {"purpose": list(range(21))}}, ValueError),
    ],
    ids=[
        "action",
        "target",
        "uuid",
        "outcome",
        "correlation",
        "time",
        "keys",
        "object",
        "nonfinite",
        "list-limit",
    ],
)
def test_invalid_evidence_cannot_bypass_shared_validation(
    changes: dict[str, object], error_type: type[Exception], evidence: AuditData, uow_spy: Mock
) -> None:
    # Deliberately bypass static field types only for malformed-input test cases.
    event = SnapshotEvent(replace(evidence, **cast(Any, changes)))
    with pytest.raises(error_type):
        record_event(cast(UnitOfWork, uow_spy), event)
    assert uow_spy.mock_calls == []


def test_event_conversion_failure_propagates_without_staging(uow_spy: Mock) -> None:
    class BrokenEvent:
        def to_record(self) -> AuditData:
            raise RuntimeError("conversion failed")

    with pytest.raises(RuntimeError, match="conversion failed"):
        record_event(cast(UnitOfWork, uow_spy), BrokenEvent())
    assert uow_spy.mock_calls == []


def test_staging_failure_is_not_swallowed_or_committed(evidence: AuditData, uow_spy: Mock) -> None:
    uow_spy.session.add.side_effect = RuntimeError("session unavailable")
    with pytest.raises(RuntimeError, match="session unavailable"):
        record_event(cast(UnitOfWork, uow_spy), SnapshotEvent(evidence))
    assert len(uow_spy.mock_calls) == 1
    uow_spy.commit.assert_not_called()
    uow_spy.rollback.assert_not_called()
