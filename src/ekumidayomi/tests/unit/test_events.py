"""Unit tests for the domain event envelope."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from ekumidayomi.events import DomainEvent


def build_event(**overrides: object) -> DomainEvent:
    values: dict[str, object] = {
        "event_id": uuid4(),
        "event_type": "product_updated",
        "aggregate_type": "product",
        "aggregate_id": uuid4(),
        "aggregate_version": 1,
        "occurred_at": datetime(2026, 1, 1, 13, tzinfo=timezone(timedelta(hours=1))),
        "payload": {"name": "Dress", "sizes": ["s", "m"], "details": {"active": True}},
    }
    values.update(overrides)
    return DomainEvent(**values)  # type: ignore[arg-type]


def test_event_is_utc_immutable_and_returns_detached_payload() -> None:
    event = build_event()

    assert event.occurred_at == datetime(2026, 1, 1, 12, tzinfo=UTC)
    with pytest.raises(FrozenInstanceError):
        event.aggregate_version = 2  # type: ignore[misc]
    with pytest.raises(TypeError):
        event.payload["name"] = "Changed"  # type: ignore[index]

    payload = event.payload_dict()
    assert payload == {
        "name": "Dress",
        "sizes": ["s", "m"],
        "details": {"active": True},
    }
    payload["name"] = "Changed"
    assert event.payload["name"] == "Dress"


@pytest.mark.parametrize("field", ["event_id", "aggregate_id"])
def test_event_requires_uuid_identifiers(field: str) -> None:
    with pytest.raises(TypeError, match="UUID"):
        build_event(**{field: "not-a-uuid"})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_type", "ProductUpdated"),
        ("aggregate_type", ""),
        ("event_type", "x" * 101),
        ("event_type", 1),
    ],
)
def test_event_requires_bounded_snake_case_types(field: str, value: object) -> None:
    with pytest.raises(ValueError, match="snake case"):
        build_event(**{field: value})


@pytest.mark.parametrize("version", [True, 1.5, "1"])
def test_event_version_must_be_an_integer(version: object) -> None:
    with pytest.raises(TypeError, match="integer"):
        build_event(aggregate_version=version)


def test_event_version_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        build_event(aggregate_version=0)


@pytest.mark.parametrize("occurred_at", [datetime(2026, 1, 1), "now"])
def test_event_requires_aware_datetime(occurred_at: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        build_event(occurred_at=occurred_at)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {1: "value"},
        {"BadKey": "value"},
        {"access_token": "secret"},
        {"value": object()},
        {"value": float("inf")},
        {"value": "x" * 10_001},
    ],
)
def test_event_rejects_unsafe_payloads(payload: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        build_event(payload=payload)


def test_event_rejects_excessive_payload_depth_and_values() -> None:
    nested: object = "value"
    for _ in range(9):
        nested = {"child": nested}
    with pytest.raises(ValueError, match="nesting"):
        build_event(payload={"root": nested})
    with pytest.raises(ValueError, match="too many"):
        build_event(payload={"values": list(range(501))})
