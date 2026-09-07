"""Tests for dependency-free shared value contracts."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest

from ekumidayomi.core.types import (
    CURRENCY_CODE_LENGTH,
    DEFAULT_CURRENCY,
    MONEY_PRECISION,
    MONEY_QUANTUM,
    MONEY_SCALE,
    DecimalInput,
    Money,
    Page,
    PageRequest,
    new_entity_id,
    normalize_currency,
    quantize_money,
    require_utc,
    serialize_entity_id,
    serialize_utc,
    utc_now,
)


def test_shared_money_and_currency_conventions() -> None:
    assert DEFAULT_CURRENCY == "NGN"
    assert CURRENCY_CODE_LENGTH == 3
    assert MONEY_PRECISION == 19
    assert MONEY_SCALE == 4
    assert MONEY_QUANTUM == Decimal("0.0001")


@pytest.mark.parametrize(
    ("value", "expected"),
    [("ngn", "NGN"), (" NGN ", "NGN"), ("usd", "USD")],
)
def test_normalize_currency_returns_uppercase_three_letter_code(
    value: str,
    expected: str,
) -> None:
    assert normalize_currency(value) == expected


@pytest.mark.parametrize("value", ["", "NG", "NGNN", "N1N", "N-N", "N₦N"])
def test_normalize_currency_rejects_invalid_codes(value: str) -> None:
    with pytest.raises(ValueError, match="three-letter ASCII"):
        normalize_currency(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal(10), Decimal("10.0000")),
        ("10.12567", Decimal("10.1257")),
        ("-1.23456", Decimal("-1.2346")),
    ],
)
def test_quantize_money_accepts_exact_inputs(
    value: DecimalInput,
    expected: Decimal,
) -> None:
    assert quantize_money(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("10.00005", Decimal("10.0000")),
        ("10.00015", Decimal("10.0002")),
        ("-10.00005", Decimal("-10.0000")),
        ("-10.00015", Decimal("-10.0002")),
    ],
)
def test_quantize_money_uses_round_half_even(value: str, expected: Decimal) -> None:
    assert quantize_money(value) == expected


@pytest.mark.parametrize("value", [True, 10, 10.25])
def test_quantize_money_rejects_inexact_runtime_types(value: object) -> None:
    with pytest.raises(TypeError):
        quantize_money(cast("DecimalInput", value))


@pytest.mark.parametrize("value", ["not-money", "", "--10"])
def test_quantize_money_rejects_invalid_decimal_strings(value: str) -> None:
    with pytest.raises(ValueError, match="valid decimal"):
        quantize_money(value)


def test_money_direct_construction_normalizes_amount_and_currency() -> None:
    result = Money(amount=Decimal("10.55555"), currency=" ngn ")

    assert result.amount == Decimal("10.5556")
    assert result.currency == "NGN"


def test_money_factory_defaults_to_ngn() -> None:
    result = Money.from_value(amount="50")

    assert result == Money(amount=Decimal("50.0000"), currency="NGN")


def test_money_is_immutable_after_construction() -> None:
    money = Money.from_value(amount="10")

    with pytest.raises(FrozenInstanceError):
        setattr(money, "amount", Decimal(20))  # noqa: B010


def test_money_addition_preserves_currency_and_scale() -> None:
    result = Money.from_value(amount="10.1255") + Money.from_value(amount="2.1000")

    assert result == Money(amount=Decimal("12.2255"), currency="NGN")


def test_money_subtraction_preserves_signed_results_and_scale() -> None:
    result = Money.from_value(amount="2.1000") - Money.from_value(amount="10.1255")

    assert result == Money(amount=Decimal("-8.0255"), currency="NGN")


@pytest.mark.parametrize("operator", ["add", "subtract"])
def test_money_rejects_mixed_currency_arithmetic(operator: str) -> None:
    naira = Money.from_value(amount="10", currency="NGN")
    dollars = Money.from_value(amount="2", currency="USD")

    with pytest.raises(ValueError, match="currency mismatch"):
        _ = naira + dollars if operator == "add" else naira - dollars


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
    page = Page(items=(UUID(int=1), UUID(int=2)), total_items=5, page=2, page_size=2)

    assert page.to_dict(str) == {
        "items": [
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
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
