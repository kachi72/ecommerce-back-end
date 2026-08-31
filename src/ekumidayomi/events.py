"""Dependency-free domain event contracts."""

from __future__ import annotations

import math
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Protocol, cast
from uuid import UUID

from ekumidayomi.core.types import require_utc

type EventJsonValue = (
    bool | int | float | str | tuple[EventJsonValue, ...] | Mapping[str, EventJsonValue] | None
)
type EventHandler = Callable[[DomainEvent, str], Awaitable[None]]

_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_SENSITIVE_KEY_PARTS = frozenset(
    {
        "authorization",
        "card",
        "cookie",
        "credential",
        "cvv",
        "password",
        "secret",
        "token",
    }
)
_MAX_PAYLOAD_DEPTH = 8
_MAX_PAYLOAD_VALUES = 500
_MAX_PAYLOAD_STRING_LENGTH = 10_000


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """An immutable, versioned fact emitted by one aggregate."""

    event_id: UUID
    event_type: str
    aggregate_type: str
    aggregate_id: UUID
    aggregate_version: int
    occurred_at: datetime
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, UUID):
            raise TypeError("event_id must be a UUID")
        _validate_type("event_type", self.event_type)
        _validate_type("aggregate_type", self.aggregate_type)
        if not isinstance(self.aggregate_id, UUID):
            raise TypeError("aggregate_id must be a UUID")
        if isinstance(self.aggregate_version, bool) or not isinstance(self.aggregate_version, int):
            raise TypeError("aggregate_version must be an integer")
        if self.aggregate_version < 1:
            raise ValueError("aggregate_version must be positive")
        if not isinstance(self.payload, Mapping):
            raise TypeError("event payload must be a mapping")

        occurred_at = require_utc(self.occurred_at)
        budget = [_MAX_PAYLOAD_VALUES]
        payload = _freeze_mapping(
            cast(Mapping[object, object], self.payload),
            depth=1,
            budget=budget,
        )
        object.__setattr__(self, "occurred_at", occurred_at)
        object.__setattr__(self, "payload", payload)

    def payload_dict(self) -> dict[str, object]:
        """Return a detached JSON-safe payload for persistence or transport."""

        return {
            key: _thaw_value(cast(EventJsonValue, value)) for key, value in self.payload.items()
        }


class EventPublisher(Protocol):
    """Provider-neutral event publisher contract."""

    async def publish(self, event: DomainEvent, idempotency_key: str) -> None: ...


def _validate_type(name: str, value: object) -> None:
    if not isinstance(value, str) or len(value) > 100 or _TYPE_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} must use lowercase snake case and at most 100 characters")


def _freeze_mapping(
    value: Mapping[object, object],
    *,
    depth: int,
    budget: list[int],
) -> Mapping[str, EventJsonValue]:
    frozen: dict[str, EventJsonValue] = {}
    for key, item in value.items():
        validated_key = _validate_payload_key(key)
        frozen[validated_key] = _freeze_value(item, depth=depth, budget=budget)
    return MappingProxyType(frozen)


def _freeze_value(value: object, *, depth: int, budget: list[int]) -> EventJsonValue:
    if depth > _MAX_PAYLOAD_DEPTH:
        raise ValueError("event payload exceeds the maximum nesting depth")
    budget[0] -= 1
    if budget[0] < 0:
        raise ValueError("event payload contains too many values")

    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("event payload must contain finite numbers")
        return value
    if isinstance(value, str):
        if len(value) > _MAX_PAYLOAD_STRING_LENGTH:
            raise ValueError("event payload strings must not exceed 10000 characters")
        return value
    if isinstance(value, list | tuple):
        return tuple(_freeze_value(item, depth=depth + 1, budget=budget) for item in value)
    if isinstance(value, Mapping):
        return _freeze_mapping(value, depth=depth + 1, budget=budget)
    raise TypeError("event payload must contain only JSON-safe values")


def _validate_payload_key(key: object) -> str:
    if not isinstance(key, str):
        raise TypeError("event payload keys must be strings")
    if len(key) > 100 or _KEY_PATTERN.fullmatch(key) is None:
        raise ValueError("event payload keys must use lowercase snake case")
    if set(key.split("_")) & _SENSITIVE_KEY_PARTS:
        raise ValueError("event payload contains a sensitive key")
    return key


def _thaw_value(value: EventJsonValue) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_value(item) for item in value]
    return value
