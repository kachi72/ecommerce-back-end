"""Dependency-free value contracts shared by application domains.

Money is persisted as an integer number of minor units (kobo). PostgreSQL
integer columns, rather than binary floating-point columns, own that persisted
representation. Currency conversion and fractional-kobo rounding are outside
the version-one contract.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from functools import total_ordering
from types import NotImplementedType
from typing import NewType, Self
from uuid import UUID, uuid4

EntityId = NewType("EntityId", UUID)


class Currency(StrEnum):
    """Currencies supported by the application."""

    NGN = "NGN"


@total_ordering
@dataclass(frozen=True, slots=True)
class Money:
    """A non-negative amount represented in integer kobo."""

    amount_kobo: int
    currency: Currency = Currency.NGN

    def __post_init__(self) -> None:
        if isinstance(self.amount_kobo, bool) or not isinstance(self.amount_kobo, int):
            raise TypeError("amount_kobo must be an integer")
        if self.amount_kobo < 0:
            raise ValueError("amount_kobo must be non-negative")

        try:
            currency = Currency(self.currency)
        except (TypeError, ValueError) as error:
            raise ValueError(f"unsupported currency: {self.currency!r}") from error
        object.__setattr__(self, "currency", currency)

    def __add__(self, other: object) -> Self | NotImplementedType:
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return type(self)(self.amount_kobo + other.amount_kobo, self.currency)

    def __sub__(self, other: object) -> Self | NotImplementedType:
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return type(self)(self.amount_kobo - other.amount_kobo, self.currency)

    def __lt__(self, other: object) -> bool | NotImplementedType:
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return self.amount_kobo < other.amount_kobo

    def to_dict(self) -> dict[str, int | str]:
        """Return the stable JSON-safe money representation."""

        return {"amount_kobo": self.amount_kobo, "currency": self.currency.value}

    def _require_same_currency(self, other: Money) -> None:
        if self.currency is not other.currency:
            raise ValueError("money values must use the same currency")


@dataclass(frozen=True, slots=True)
class PageRequest:
    """Validated one-based pagination inputs."""

    page: int = 1
    page_size: int = 20

    def __post_init__(self) -> None:
        _require_integer("page", self.page)
        _require_integer("page_size", self.page_size)
        if self.page < 1:
            raise ValueError("page must be at least 1")
        if not 1 <= self.page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")

    @property
    def offset(self) -> int:
        """Return the zero-based storage offset for this request."""

        return (self.page - 1) * self.page_size

    def to_dict(self) -> dict[str, int]:
        """Return JSON-safe pagination inputs."""

        return {"page": self.page, "page_size": self.page_size}


@dataclass(frozen=True, slots=True)
class Page[T]:
    """An immutable page of results and its response metadata."""

    items: tuple[T, ...]
    total_items: int
    page: int = 1
    page_size: int = 20

    def __post_init__(self) -> None:
        request = PageRequest(page=self.page, page_size=self.page_size)
        _require_integer("total_items", self.total_items)
        if self.total_items < 0:
            raise ValueError("total_items must be non-negative")

        items = tuple(self.items)
        if len(items) > request.page_size:
            raise ValueError("items cannot exceed page_size")
        if len(items) > self.total_items:
            raise ValueError("items cannot exceed total_items")
        object.__setattr__(self, "items", items)

    @property
    def total_pages(self) -> int:
        """Return the number of pages, or zero for an empty result."""

        return (self.total_items + self.page_size - 1) // self.page_size

    @property
    def has_previous(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages

    def to_dict(
        self,
        item_serializer: Callable[[T], object] | None = None,
    ) -> dict[str, object]:
        """Return items and pagination metadata in a JSON-safe envelope.

        Callers whose item type is not already JSON-safe provide an explicit
        serializer. Shared pagination metadata never depends on a web framework.
        """

        serialized_items = [
            item_serializer(item) if item_serializer is not None else item for item in self.items
        ]
        return {
            "items": serialized_items,
            "pagination": {
                "page": self.page,
                "page_size": self.page_size,
                "total_items": self.total_items,
                "total_pages": self.total_pages,
                "has_previous": self.has_previous,
                "has_next": self.has_next,
            },
        }


def new_entity_id() -> EntityId:
    """Create a new domain entity identifier."""

    return EntityId(uuid4())


def serialize_entity_id(value: EntityId | UUID) -> str:
    """Return the canonical JSON-safe UUID representation."""

    if not isinstance(value, UUID):
        raise TypeError("entity identifier must be a UUID")
    return str(value)


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""

    return datetime.now(UTC)


def require_utc(value: datetime) -> datetime:
    """Reject naive timestamps and normalize aware timestamps to UTC."""

    if not isinstance(value, datetime):
        raise TypeError("value must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


def serialize_utc(value: datetime) -> str:
    """Return a normalized ISO 8601 timestamp using the UTC ``Z`` suffix."""

    return require_utc(value).isoformat().replace("+00:00", "Z")


def _require_integer(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
