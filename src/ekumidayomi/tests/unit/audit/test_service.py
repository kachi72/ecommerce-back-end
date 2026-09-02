"""Audit service, sanitizer, actor, and filter tests."""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone
from typing import cast
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from ekumidayomi.audit.model import ActorKind, AuditOutcome
from ekumidayomi.audit.service import (
    REDACTED_VALUE,
    AuditActor,
    AuditFilters,
    record,
    sanitize_audit_metadata,
)
from ekumidayomi.db.uow import UnitOfWork


def make_uow() -> tuple[UnitOfWork, Mock]:
    session = Mock()
    uow = Mock(spec=UnitOfWork)
    uow.session = session
    return cast(UnitOfWork, uow), session


def test_record_stages_sanitized_audit_in_the_existing_transaction() -> None:
    uow, session = make_uow()
    target_id = UUID("00000000-0000-4000-8000-000000000001")
    occurred_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    audit = record(
        uow,
        actor=AuditActor(ActorKind.SYSTEM),
        action="product.created",
        target_type="product",
        target_id=target_id,
        outcome=AuditOutcome.SUCCEEDED,
        metadata={"source": "admin", "password": "never-store", "unknown": "drop"},
        allowed_metadata_keys=frozenset({"source", "password"}),
        correlation_id="request-1",
        occurred_at=occurred_at,
    )

    assert audit.actor_kind == "system"
    assert audit.actor_id is None
    assert audit.action == "product.created"
    assert audit.target_type == "product"
    assert audit.target_id == target_id
    assert audit.outcome == "succeeded"
    assert audit.occurred_at == occurred_at
    assert audit.correlation_id == "request-1"
    assert audit.metadata_ == {
        "source": "admin",
        "password": REDACTED_VALUE,
    }
    session.add.assert_called_once_with(audit)


def test_sanitizer_allowlists_redacts_and_normalizes_nested_metadata() -> None:
    identifier = UUID("00000000-0000-4000-8000-000000000001")
    occurred_at = datetime(
        2026,
        1,
        1,
        13,
        0,
        tzinfo=timezone(timedelta(hours=1)),
    )
    metadata = {
        "source": "admin",
        "password": "never-store",
        "nested": {
            "session_token_hash": "never-store",
            "kept": "visible",
            "unknown_nested": "drop-me",
        },
        "identifiers": [identifier],
        "occurred_at": occurred_at,
        "discarded_count": 2,
        "values": (True, 3, 2.5, None),
        "unknown": "drop-me",
    }

    assert sanitize_audit_metadata(
        metadata,
        allowed_keys=frozenset(
            {
                "source",
                "password",
                "nested",
                "session_token_hash",
                "kept",
                "identifiers",
                "occurred_at",
                "discarded_count",
                "values",
            }
        ),
    ) == {
        "source": "admin",
        "password": REDACTED_VALUE,
        "nested": {
            "session_token_hash": REDACTED_VALUE,
            "kept": "visible",
        },
        "identifiers": [str(identifier)],
        "occurred_at": "2026-01-01T12:00:00Z",
        "discarded_count": 2,
        "values": [True, 3, 2.5, None],
    }


def test_sanitizer_truncates_strings_and_accepts_empty_metadata() -> None:
    assert sanitize_audit_metadata({}, allowed_keys=frozenset()) == {}
    assert sanitize_audit_metadata(
        {"reason": "x" * 501},
        allowed_keys=frozenset({"reason"}),
    ) == {"reason": "x" * 500}


@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")])
def test_sanitizer_rejects_non_finite_numbers(number: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        sanitize_audit_metadata(
            {"number": number},
            allowed_keys=frozenset({"number"}),
        )


@pytest.mark.parametrize(
    "metadata,message",
    [
        ({"items": list(range(21))}, "too many items"),
        ({"value": b"not-json"}, "unsupported value"),
        (
            {"level": {"level": {"level": {"level": {"level": "too deep"}}}}},
            "nesting limit",
        ),
    ],
)
def test_sanitizer_rejects_unsafe_or_unbounded_values(
    metadata: dict[str, object],
    message: str,
) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        sanitize_audit_metadata(
            metadata,
            allowed_keys=frozenset({"items", "value", "level"}),
        )


def test_sanitizer_rejects_naive_timestamps() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        sanitize_audit_metadata(
            {"occurred_at": datetime(2026, 1, 1)},
            allowed_keys=frozenset({"occurred_at"}),
        )


def test_sanitizer_enforces_mapping_value_and_byte_limits() -> None:
    too_many_fields = {f"field_{index}": index for index in range(51)}
    with pytest.raises(ValueError, match="mapping contains too many"):
        sanitize_audit_metadata(
            too_many_fields,
            allowed_keys=frozenset(too_many_fields),
        )

    too_many_values = {f"items_{index}": list(range(20)) for index in range(5)}
    with pytest.raises(ValueError, match="too many values"):
        sanitize_audit_metadata(
            too_many_values,
            allowed_keys=frozenset(too_many_values),
        )

    oversized = {f"field_{index}": "x" * 500 for index in range(40)}
    with pytest.raises(ValueError, match="byte limit"):
        sanitize_audit_metadata(
            oversized,
            allowed_keys=frozenset(oversized),
        )


def test_sanitizer_validates_mapping_keys_and_allowlist() -> None:
    with pytest.raises(TypeError, match="must be a mapping"):
        sanitize_audit_metadata([], allowed_keys=frozenset())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="keys must be strings"):
        sanitize_audit_metadata(
            cast(Mapping[str, object], {1: "value"}),
            allowed_keys=frozenset({"value"}),
        )
    with pytest.raises(TypeError, match="must be a frozenset"):
        sanitize_audit_metadata({}, allowed_keys=set())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="safe snake case"):
        sanitize_audit_metadata({}, allowed_keys=frozenset({"Unsafe-Key"}))

    too_many_allowed = frozenset(f"key_{index}" for index in range(101))
    with pytest.raises(ValueError, match="too many allowed"):
        sanitize_audit_metadata({}, allowed_keys=too_many_allowed)


def test_audit_actor_requires_an_identifier_only_for_human_actors() -> None:
    identifier = uuid4()

    assert AuditActor(ActorKind.CUSTOMER, identifier).actor_id == identifier
    assert AuditActor(ActorKind.ADMINISTRATOR, identifier).actor_id == identifier
    assert AuditActor(ActorKind.SYSTEM).actor_id is None
    assert AuditActor(ActorKind.ANONYMOUS).actor_id is None
    with pytest.raises(ValueError, match="require actor_id"):
        AuditActor(ActorKind.ADMINISTRATOR)
    with pytest.raises(ValueError, match="cannot have actor_id"):
        AuditActor(ActorKind.ANONYMOUS, identifier)
    with pytest.raises(TypeError, match="must be a UUID"):
        AuditActor(ActorKind.CUSTOMER, "not-a-uuid")  # type: ignore[arg-type]


def test_audit_filters_normalize_values_and_utc_ranges() -> None:
    actor_id = uuid4()
    target_id = uuid4()
    occurred_from = datetime(2026, 1, 1, 13, 0, tzinfo=timezone(timedelta(hours=1)))
    occurred_to = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)

    filters = AuditFilters(
        action="product.created",
        actor_kind=ActorKind.ADMINISTRATOR,
        actor_id=actor_id,
        target_type="product",
        target_id=target_id,
        outcome=AuditOutcome.SUCCEEDED,
        correlation_id="request-1",
        occurred_from=occurred_from,
        occurred_to=occurred_to,
    )

    assert filters.actor_kind is ActorKind.ADMINISTRATOR
    assert filters.actor_id == actor_id
    assert filters.target_id == target_id
    assert filters.outcome is AuditOutcome.SUCCEEDED
    assert filters.occurred_from == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert filters.occurred_to == occurred_to


def test_audit_filters_reject_invalid_values() -> None:
    now = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)

    with pytest.raises(ValueError, match="must not be after"):
        AuditFilters(occurred_from=now, occurred_to=now - timedelta(days=1))
    with pytest.raises(ValueError, match="action"):
        AuditFilters(action="Unsafe action")
    with pytest.raises(ValueError, match="target_type"):
        AuditFilters(target_type="")
    with pytest.raises(ValueError, match="correlation_id"):
        AuditFilters(correlation_id="unsafe correlation")
    with pytest.raises(ValueError, match="timezone-aware"):
        AuditFilters(occurred_from=datetime(2026, 1, 1))
    with pytest.raises(TypeError, match="actor_id"):
        AuditFilters(actor_id="bad")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="target_id"):
        AuditFilters(target_id="bad")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("overrides", "error_type", "message"),
    [
        ({"action": "Unsafe action"}, ValueError, "action"),
        ({"target_type": ""}, ValueError, "target_type"),
        ({"target_id": "bad"}, TypeError, "target_id"),
        ({"outcome": "unknown"}, ValueError, "unknown"),
        ({"correlation_id": "unsafe correlation"}, ValueError, "correlation_id"),
        ({"occurred_at": datetime(2026, 1, 1)}, ValueError, "timezone-aware"),
    ],
)
def test_record_rejects_invalid_contract_values(
    overrides: dict[str, object],
    error_type: type[Exception],
    message: str,
) -> None:
    uow, _ = make_uow()
    arguments: dict[str, object] = {
        "actor": AuditActor(ActorKind.SYSTEM),
        "action": "product.created",
        "target_type": "product",
        "target_id": uuid4(),
        "outcome": AuditOutcome.SUCCEEDED,
        "metadata": {},
        "allowed_metadata_keys": frozenset(),
        "correlation_id": "request-1",
        "occurred_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    arguments.update(overrides)

    with pytest.raises(error_type, match=message):
        record(uow, **arguments)  # type: ignore[arg-type]
