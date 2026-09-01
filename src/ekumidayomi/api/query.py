"""Validated query conventions shared by versioned HTTP routes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Query

from ekumidayomi.core.types import PageRequest

_FIELD_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MAX_SORT_FIELDS = 10
_MAX_FILTERS = 20
_MAX_QUERY_VALUE_LENGTH = 500


def pagination(
    page: Annotated[int, Query(ge=1, examples=[1])] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, examples=[20])] = 20,
) -> PageRequest:
    """Return bounded, one-based pagination inputs."""

    return PageRequest(page=page, page_size=page_size)


@dataclass(frozen=True, slots=True)
class SortField:
    """One allowlisted field and its requested ordering direction."""

    name: str
    direction: Literal["asc", "desc"]


def parse_sort(value: str | None, *, allowed: frozenset[str]) -> tuple[SortField, ...]:
    """Parse comma-separated sorting and add a deterministic identifier tie-breaker."""

    _validate_allowed_fields(allowed, require_id=True)
    if value is not None and len(value) > _MAX_QUERY_VALUE_LENGTH:
        raise ValueError("sort value is too long")

    raw_fields = value.split(",") if value else []
    if len(raw_fields) > _MAX_SORT_FIELDS:
        raise ValueError(f"sorting supports at most {_MAX_SORT_FIELDS} fields")

    fields: list[SortField] = []
    seen: set[str] = set()
    for raw in raw_fields:
        direction: Literal["asc", "desc"] = "desc" if raw.startswith("-") else "asc"
        name = raw.removeprefix("-")
        if not _FIELD_PATTERN.fullmatch(name) or name not in allowed:
            raise ValueError(f"sorting by {name!r} is not allowed")
        if name in seen:
            raise ValueError("sort fields must be unique")
        seen.add(name)
        fields.append(SortField(name=name, direction=direction))

    if "id" not in seen:
        fields.append(SortField(name="id", direction="asc"))
    return tuple(fields)


def parse_filters(values: list[str] | None, *, allowed: frozenset[str]) -> dict[str, str]:
    """Parse unique allowlisted ``field:value`` filters without interpreting values."""

    _validate_allowed_fields(allowed)
    raw_filters = values or []
    if len(raw_filters) > _MAX_FILTERS:
        raise ValueError(f"filtering supports at most {_MAX_FILTERS} fields")

    parsed: dict[str, str] = {}
    for raw in raw_filters:
        if len(raw) > _MAX_QUERY_VALUE_LENGTH:
            raise ValueError("filter value is too long")
        name, separator, value = raw.partition(":")
        if (
            not separator
            or not value
            or value != value.strip()
            or not _FIELD_PATTERN.fullmatch(name)
            or name not in allowed
            or name in parsed
        ):
            raise ValueError("filter must use one unique allowed field:value pair")
        parsed[name] = value
    return parsed


def _validate_allowed_fields(allowed: frozenset[str], *, require_id: bool = False) -> None:
    if not allowed or any(not _FIELD_PATTERN.fullmatch(item) for item in allowed):
        raise ValueError("allowed fields must contain safe field names")
    if require_id and "id" not in allowed:
        raise ValueError("allowed sort fields must include id")
