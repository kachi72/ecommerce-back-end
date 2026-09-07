"""Dependency-free value contracts shared by application domains.

Money uses exact Decimal inputs and four-place round-half-even normalization.
Persistence adapters use PostgreSQL NUMERIC(19, 4); API adapters use fixed-scale
strings. Currency defaults to NGN, while signed amounts and other normalized
three-letter currencies remain valid in this shared contract.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Final, NewType
from uuid import UUID, uuid4

EntityId = NewType("EntityId", UUID)


type DecimalInput = Decimal | str

DEFAULT_CURRENCY: Final = "NGN"
CURRENCY_CODE_LENGTH: Final = 3
MONEY_PRECISION: Final = 19
MONEY_SCALE: Final = 4
MONEY_QUANTUM: Final = Decimal("0.0001")


def normalize_currency(value: str) -> str:
    """Return a normalized three-letter ASCII currency code."""
    currency = value.strip().upper()
    if len(currency) != CURRENCY_CODE_LENGTH or not currency.isascii() or not currency.isalpha():
        msg = "currency must be a three-letter ASCII code"
        raise ValueError(msg)
    return currency


def quantize_money(value: DecimalInput) -> Decimal:
    """Convert an exact input to the project's four-place monetary scale."""
    if isinstance(value, bool):
        msg = "boolean values are not valid monetary amounts"
        raise TypeError(msg)
    if isinstance(value, float):
        msg = "floating-point values are not valid monetary amounts"
        raise TypeError(msg)
    if isinstance(value, int):
        msg = "integer values are not valid monetary amounts"
        raise TypeError(msg)
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, ValueError) as error:
        msg = "money must be a valid decimal value"
        raise ValueError(msg) from error
    return decimal_value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True, slots=True)
class Money:
    """An exact monetary amount paired with a normalized currency."""

    amount: Decimal
    currency: str = DEFAULT_CURRENCY

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", quantize_money(self.amount))
        object.__setattr__(self, "currency", normalize_currency(self.currency))

    @classmethod
    def from_value(cls, *, amount: DecimalInput, currency: str = DEFAULT_CURRENCY) -> Money:
        """Build money without permitting binary floating-point input."""
        return cls(amount=quantize_money(amount), currency=currency)

    def __add__(self, other: Money) -> Money:
        self._require_same_currency(other)
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def __sub__(self, other: Money) -> Money:
        self._require_same_currency(other)
        return Money(amount=self.amount - other.amount, currency=self.currency)

    def _require_same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            msg = f"currency mismatch: {self.currency} != {other.currency}"
            raise ValueError(msg)


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
