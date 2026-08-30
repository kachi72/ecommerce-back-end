"""Tests for dependency-free shared value contracts."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from ekumidayomi.core.types import (
    Currency,
    Money,
    Page,
    PageRequest,
    new_entity_id,
    require_utc,
    serialize_entity_id,
    serialize_utc,
    utc_now,
)


@pytest.mark.parametrize("amount", [True, False, 10.5, "100"])
def test_money_rejects_non_integer_kobo(amount: object) -> None:
    with pytest.raises(TypeError, match="must be an integer"):
        Money(amount)  # type: ignore[arg-type]


def test_money_rejects_negative_kobo() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        Money(-1)


def test_money_rejects_unsupported_currency() -> None:
    with pytest.raises(ValueError, match="unsupported currency"):
        Money(100, "USD")  # type: ignore[arg-type]


def test_money_serializes_with_explicit_ngn_currency() -> None:
    money = Money(125_050)

    assert money.currency is Currency.NGN
    assert money.to_dict() == {
        "amount_kobo": 125_050,
        "currency": "NGN",
    }


def test_money_is_immutable() -> None:
    money = Money(100)

    with pytest.raises(AttributeError):
        money.amount_kobo = 200  # type: ignore[misc]


def test_money_supports_same_currency_arithmetic_and_ordering() -> None:
    smaller = Money(150)
    larger = Money(250)

    assert smaller + larger == Money(400)
    assert larger - smaller == Money(100)
    assert smaller < larger
    assert larger > smaller


def test_money_subtraction_cannot_create_a_negative_amount() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        Money(100) - Money(101)


def test_money_rejects_arithmetic_with_an_unrelated_value() -> None:
    with pytest.raises(TypeError):
        Money(100) + 100


def test_money_rejects_subtraction_with_an_unrelated_value() -> None:
    with pytest.raises(TypeError):
        Money(100) - 100


def test_money_rejects_ordering_with_an_unrelated_value() -> None:
    with pytest.raises(TypeError):
        _ = Money(100) < 100


def test_money_rejects_currency_mismatch() -> None:
    ngn = Money(100)
    other = Money(100)
    object.__setattr__(other, "currency", "USD")

    with pytest.raises(ValueError, match="same currency"):
        ngn + other
    with pytest.raises(ValueError, match="same currency"):
        _ = ngn < other


def test_new_entity_id_returns_unique_uuids() -> None:
    first = new_entity_id()
    second = new_entity_id()

    assert isinstance(first, UUID)
    assert first != second
    assert serialize_entity_id(first) == str(first)


def test_entity_id_serializer_rejects_non_uuid_values() -> None:
    with pytest.raises(TypeError, match="must be a UUID"):
        serialize_entity_id("not-a-uuid")  # type: ignore[arg-type]


def test_utc_now_returns_an_aware_utc_timestamp() -> None:
    value = utc_now()

    assert value.tzinfo is UTC
    assert value.utcoffset() == timedelta(0)


def test_require_utc_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        require_utc(datetime(2026, 8, 30, 12, 0))


def test_require_utc_rejects_non_datetime_value() -> None:
    with pytest.raises(TypeError, match="must be a datetime"):
        require_utc("2026-08-30T12:00:00Z")  # type: ignore[arg-type]


def test_require_utc_normalizes_an_aware_datetime() -> None:
    lagos_time = datetime(2026, 8, 30, 13, 30, tzinfo=timezone(timedelta(hours=1)))

    assert require_utc(lagos_time) == datetime(2026, 8, 30, 12, 30, tzinfo=UTC)


def test_utc_serializer_uses_the_z_suffix() -> None:
    value = datetime(2026, 8, 30, 13, 30, 45, tzinfo=timezone(timedelta(hours=1)))

    assert serialize_utc(value) == "2026-08-30T12:30:45Z"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("page", 0, "page must be at least 1"),
        ("page", -1, "page must be at least 1"),
        ("page_size", 0, "page_size must be between 1 and 100"),
        ("page_size", 101, "page_size must be between 1 and 100"),
    ],
)
def test_page_request_rejects_out_of_bounds_values(
    field: str,
    value: int,
    message: str,
) -> None:
    values = {"page": 1, "page_size": 20, field: value}

    with pytest.raises(ValueError, match=message):
        PageRequest(**values)


@pytest.mark.parametrize("field", ["page", "page_size"])
@pytest.mark.parametrize("value", [True, 1.5])
def test_page_request_rejects_non_integer_values(field: str, value: object) -> None:
    values = {"page": 1, "page_size": 20, field: value}

    with pytest.raises(TypeError, match=f"{field} must be an integer"):
        PageRequest(**values)  # type: ignore[arg-type]


def test_page_request_exposes_offset_and_json_safe_values() -> None:
    request = PageRequest(page=3, page_size=25)

    assert request.offset == 50
    assert request.to_dict() == {"page": 3, "page_size": 25}


def test_page_serializes_items_and_metadata() -> None:
    page = Page(items=(Money(100), Money(200)), total_items=5, page=2, page_size=2)

    assert page.to_dict(Money.to_dict) == {
        "items": [
            {"amount_kobo": 100, "currency": "NGN"},
            {"amount_kobo": 200, "currency": "NGN"},
        ],
        "pagination": {
            "page": 2,
            "page_size": 2,
            "total_items": 5,
            "total_pages": 3,
            "has_previous": True,
            "has_next": True,
        },
    }


def test_empty_page_has_zero_total_pages() -> None:
    page: Page[str] = Page(items=(), total_items=0)

    assert page.total_pages == 0
    assert not page.has_previous
    assert not page.has_next


@pytest.mark.parametrize("total_items", [True, -1])
def test_page_rejects_invalid_total_items(total_items: object) -> None:
    expected_error = TypeError if isinstance(total_items, bool) else ValueError

    with pytest.raises(expected_error):
        Page(items=(), total_items=total_items)  # type: ignore[arg-type]


def test_page_rejects_more_items_than_page_size() -> None:
    with pytest.raises(ValueError, match="cannot exceed page_size"):
        Page(items=(1, 2), total_items=2, page_size=1)


def test_page_rejects_more_items_than_total() -> None:
    with pytest.raises(ValueError, match="cannot exceed total_items"):
        Page(items=(1,), total_items=0)
