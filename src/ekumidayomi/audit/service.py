"""Transaction-aware audit recording, sanitization, and private queries."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.sql.elements import ColumnElement

from ekumidayomi.audit.model import ActorKind, AuditOutcome, AuditRecord
from ekumidayomi.core.types import (
    Page,
    PageRequest,
    require_utc,
    serialize_utc,
    utc_now,
)
from ekumidayomi.db.uow import UnitOfWork

type AuditScalar = bool | int | float | str | None
type AuditValue = AuditScalar | list[AuditValue] | dict[str, AuditValue]

REDACTED_VALUE = "[REDACTED]"
_MAX_METADATA_BYTES = 16_384
_MAX_METADATA_DEPTH = 4
_MAX_MAPPING_FIELDS = 50
_MAX_LIST_ITEMS = 20
_MAX_TOTAL_VALUES = 100
_MAX_STRING_LENGTH = 500
_SAFE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._:-][a-z0-9]+)*$")
_SAFE_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,99}$")
_CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SENSITIVE_METADATA_KEY_PARTS = frozenset(
    {
        "address",
        "authorization",
        "body",
        "card",
        "cardholder",
        "connection",
        "cookie",
        "credential",
        "cvc",
        "cvv",
        "email",
        "hash",
        "ip",
        "otp",
        "pan",
        "password",
        "passwd",
        "payload",
        "phone",
        "secret",
        "session",
        "token",
    }
)


@dataclass(frozen=True, slots=True)
class AuditActor:
    """Actor context recorded without depending on future identity models."""

    kind: ActorKind
    actor_id: UUID | None = None

    def __post_init__(self) -> None:
        kind = ActorKind(self.kind)
        object.__setattr__(self, "kind", kind)
        if kind in {ActorKind.CUSTOMER, ActorKind.ADMINISTRATOR}:
            if self.actor_id is None:
                raise ValueError("customer and administrator audit actors require actor_id")
        elif self.actor_id is not None:
            raise ValueError("system and anonymous audit actors cannot have actor_id")
        if self.actor_id is not None and not isinstance(self.actor_id, UUID):
            raise TypeError("actor_id must be a UUID")


@dataclass(frozen=True, slots=True)
class AuditFilters:
    """Exact, indexed filters for future authorized audit administration."""

    action: str | None = None
    actor_kind: ActorKind | None = None
    actor_id: UUID | None = None
    target_type: str | None = None
    target_id: UUID | None = None
    outcome: AuditOutcome | None = None
    correlation_id: str | None = None
    occurred_from: datetime | None = None
    occurred_to: datetime | None = None

    def __post_init__(self) -> None:
        if self.action is not None:
            _validate_name("action", self.action, maximum=100)
        if self.target_type is not None:
            _validate_name("target_type", self.target_type, maximum=100)
        if self.actor_kind is not None:
            object.__setattr__(self, "actor_kind", ActorKind(self.actor_kind))
        if self.actor_id is not None and not isinstance(self.actor_id, UUID):
            raise TypeError("actor_id must be a UUID")
        if self.target_id is not None and not isinstance(self.target_id, UUID):
            raise TypeError("target_id must be a UUID")
        if self.outcome is not None:
            object.__setattr__(self, "outcome", AuditOutcome(self.outcome))
        if self.correlation_id is not None:
            _validate_correlation_id(self.correlation_id)
        if self.occurred_from is not None:
            object.__setattr__(self, "occurred_from", require_utc(self.occurred_from))
        if self.occurred_to is not None:
            object.__setattr__(self, "occurred_to", require_utc(self.occurred_to))
        if (
            self.occurred_from is not None
            and self.occurred_to is not None
            and self.occurred_from > self.occurred_to
        ):
            raise ValueError("occurred_from must not be after occurred_to")


def record(
    uow: UnitOfWork,
    *,
    actor: AuditActor,
    action: str,
    target_type: str,
    target_id: UUID,
    outcome: AuditOutcome,
    metadata: Mapping[str, object],
    allowed_metadata_keys: frozenset[str],
    correlation_id: str,
    occurred_at: datetime | None = None,
) -> AuditRecord:
    """Stage one immutable audit record in the caller's transaction."""

    _validate_name("action", action, maximum=100)
    _validate_name("target_type", target_type, maximum=100)
    if not isinstance(target_id, UUID):
        raise TypeError("target_id must be a UUID")
    _validate_correlation_id(correlation_id)
    resolved_outcome = AuditOutcome(outcome)
    audit = AuditRecord(
        actor_kind=actor.kind.value,
        actor_id=actor.actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        outcome=resolved_outcome.value,
        occurred_at=require_utc(occurred_at or utc_now()),
        correlation_id=correlation_id,
        metadata_=sanitize_audit_metadata(
            metadata,
            allowed_keys=allowed_metadata_keys,
        ),
    )
    uow.session.add(audit)
    return audit


async def query_records(
    uow: UnitOfWork,
    *,
    filters: AuditFilters,
    page_request: PageRequest,
) -> Page[AuditRecord]:
    """Return a deterministic private page for a future authorized admin API."""

    conditions = _conditions(filters)
    count_statement = sa.select(sa.func.count()).select_from(AuditRecord)
    records_statement = sa.select(AuditRecord)
    if conditions:
        count_statement = count_statement.where(*conditions)
        records_statement = records_statement.where(*conditions)

    total_items = int(await uow.session.scalar(count_statement) or 0)
    records = tuple(
        (
            await uow.session.scalars(
                records_statement.order_by(
                    AuditRecord.occurred_at.desc(),
                    AuditRecord.id.desc(),
                )
                .limit(page_request.page_size)
                .offset(page_request.offset)
            )
        ).all()
    )
    return Page(
        items=records,
        total_items=total_items,
        page=page_request.page,
        page_size=page_request.page_size,
    )


def sanitize_audit_metadata(
    metadata: Mapping[str, object],
    *,
    allowed_keys: frozenset[str],
) -> dict[str, AuditValue]:
    """Allowlist, redact, normalize, and bound metadata before persistence."""

    if not isinstance(metadata, Mapping):
        raise TypeError("audit metadata must be a mapping")
    _validate_allowed_keys(allowed_keys)
    sanitized = _sanitize_mapping(
        metadata,
        allowed_keys=allowed_keys,
        depth=0,
        budget=[_MAX_TOTAL_VALUES],
    )
    encoded = json.dumps(
        sanitized,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > _MAX_METADATA_BYTES:
        raise ValueError("audit metadata exceeds the byte limit")
    return sanitized


def _conditions(filters: AuditFilters) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if filters.action is not None:
        conditions.append(AuditRecord.action == filters.action)
    if filters.actor_kind is not None:
        conditions.append(AuditRecord.actor_kind == filters.actor_kind.value)
    if filters.actor_id is not None:
        conditions.append(AuditRecord.actor_id == filters.actor_id)
    if filters.target_type is not None:
        conditions.append(AuditRecord.target_type == filters.target_type)
    if filters.target_id is not None:
        conditions.append(AuditRecord.target_id == filters.target_id)
    if filters.outcome is not None:
        conditions.append(AuditRecord.outcome == filters.outcome.value)
    if filters.correlation_id is not None:
        conditions.append(AuditRecord.correlation_id == filters.correlation_id)
    if filters.occurred_from is not None:
        conditions.append(AuditRecord.occurred_at >= filters.occurred_from)
    if filters.occurred_to is not None:
        conditions.append(AuditRecord.occurred_at <= filters.occurred_to)
    return conditions


def _sanitize_mapping(
    value: Mapping[str, object],
    *,
    allowed_keys: frozenset[str],
    depth: int,
    budget: list[int],
) -> dict[str, AuditValue]:
    _validate_depth(depth)
    if len(value) > _MAX_MAPPING_FIELDS:
        raise ValueError("audit metadata mapping contains too many fields")

    output: dict[str, AuditValue] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError("audit metadata keys must be strings")
        if key not in allowed_keys:
            continue
        _consume_budget(budget)
        if _is_sensitive_key(key):
            output[key] = REDACTED_VALUE
            continue
        output[key] = _sanitize_value(
            item,
            allowed_keys=allowed_keys,
            depth=depth + 1,
            budget=budget,
        )
    return output


def _sanitize_value(
    value: object,
    *,
    allowed_keys: frozenset[str],
    depth: int,
    budget: list[int],
) -> AuditValue:
    _validate_depth(depth)
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("audit metadata numbers must be finite")
        return value
    if isinstance(value, str):
        return value[:_MAX_STRING_LENGTH]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return serialize_utc(value)
    if isinstance(value, Mapping):
        return _sanitize_mapping(
            value,
            allowed_keys=allowed_keys,
            depth=depth,
            budget=budget,
        )
    if isinstance(value, list | tuple):
        if len(value) > _MAX_LIST_ITEMS:
            raise ValueError("audit metadata list contains too many items")
        output: list[AuditValue] = []
        for item in value:
            _consume_budget(budget)
            output.append(
                _sanitize_value(
                    item,
                    allowed_keys=allowed_keys,
                    depth=depth + 1,
                    budget=budget,
                )
            )
        return output
    raise TypeError("audit metadata contains an unsupported value")


def _is_sensitive_key(key: str) -> bool:
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    parts = frozenset(re.findall(r"[a-z0-9]+", separated.casefold()))
    return not parts.isdisjoint(_SENSITIVE_METADATA_KEY_PARTS)


def _validate_allowed_keys(allowed_keys: frozenset[str]) -> None:
    if not isinstance(allowed_keys, frozenset):
        raise TypeError("allowed audit metadata keys must be a frozenset")
    if len(allowed_keys) > _MAX_TOTAL_VALUES:
        raise ValueError("too many allowed audit metadata keys")
    if any(_SAFE_KEY_PATTERN.fullmatch(key) is None for key in allowed_keys):
        raise ValueError("allowed audit metadata keys must use safe snake case")


def _validate_depth(depth: int) -> None:
    if depth > _MAX_METADATA_DEPTH:
        raise ValueError("audit metadata exceeds the nesting limit")


def _consume_budget(budget: list[int]) -> None:
    budget[0] -= 1
    if budget[0] < 0:
        raise ValueError("audit metadata contains too many values")


def _validate_name(name: str, value: object, *, maximum: int) -> None:
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or _SAFE_NAME_PATTERN.fullmatch(value) is None
    ):
        raise ValueError(f"{name} must use 1-{maximum} safe lowercase characters")


def _validate_correlation_id(value: object) -> None:
    if not isinstance(value, str) or _CORRELATION_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("correlation_id must use 1-128 safe characters")
