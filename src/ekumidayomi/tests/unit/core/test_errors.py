"""Tests for dependency-free application error contracts."""

import math
from http import HTTPStatus
from typing import Any

import pytest

from ekumidayomi.core.errors import ApplicationError, JsonValue, NotFoundError


def test_application_error_preserves_safe_contract_values() -> None:
    details: dict[str, JsonValue] = {
        "field": "email",
        "reasons": ("required", 2),
        "ratio": 1.5,
        "retry": False,
    }

    class CustomerNotFoundError(NotFoundError):
        code = "customer_not_found"
        message = "Customer was not found"

    error = CustomerNotFoundError(details=details)

    assert error.code == "customer_not_found"
    assert error.message == "Customer was not found"
    assert error.details == {
        "field": "email",
        "reasons": ["required", 2],
        "ratio": 1.5,
        "retry": False,
    }
    assert str(error) == "Customer was not found"


@pytest.mark.parametrize(
    "code",
    ["UPPER_CASE", "hyphen-code", "space code", "_leading", "trailing_", ""],
)
def test_application_error_rejects_unstable_codes(code: str) -> None:
    with pytest.raises(ValueError, match="lowercase snake case"):
        type("InvalidCodeError", (ApplicationError,), {"code": code})()


def test_application_error_rejects_non_string_code() -> None:
    with pytest.raises(ValueError, match="lowercase snake case"):
        type("InvalidCodeError", (ApplicationError,), {"code": 123})()


@pytest.mark.parametrize("message", ["", "first\nsecond", "nul\x00byte", "x" * 501])
def test_application_error_rejects_unsafe_messages(message: str) -> None:
    with pytest.raises(ValueError, match="single safe line"):
        type("InvalidMessageError", (ApplicationError,), {"message": message})()


def test_application_error_rejects_non_string_message() -> None:
    with pytest.raises(TypeError, match="must be a string"):
        type("InvalidMessageError", (ApplicationError,), {"message": 123})()


def test_application_error_rejects_non_dictionary_details() -> None:
    with pytest.raises(TypeError, match="must be a dictionary"):
        ApplicationError(
            details=[],  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "key",
    ["password", "access_token", "raw_input", "request_body", "cookie_value", "credential"],
)
def test_application_error_rejects_sensitive_detail_keys(key: str) -> None:
    with pytest.raises(ValueError, match="sensitive key"):
        ApplicationError(
            details={key: "must-not-leak"},
        )


def test_application_error_rejects_non_string_detail_keys() -> None:
    with pytest.raises(TypeError, match="keys must be strings"):
        ApplicationError(
            details={1: "value"},  # type: ignore[dict-item]
        )


@pytest.mark.parametrize("value", [object(), {1, 2}])
def test_application_error_rejects_non_json_values(value: object) -> None:
    with pytest.raises(TypeError, match="JSON-safe"):
        ApplicationError(
            details={"value": value},  # type: ignore[dict-item]
        )


@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan])
def test_application_error_rejects_non_finite_numbers(value: float) -> None:
    with pytest.raises(ValueError, match="finite numbers"):
        ApplicationError(
            details={"value": value},
        )


def test_application_error_rejects_oversized_string() -> None:
    with pytest.raises(ValueError, match="1000 characters"):
        ApplicationError(
            details={"value": "x" * 1_001},
        )


def test_application_error_rejects_excessive_depth() -> None:
    value: object = "deep"
    for _ in range(7):
        value = [value]

    with pytest.raises(ValueError, match="nesting depth"):
        ApplicationError(
            details={"value": value},  # type: ignore[dict-item]
        )


def test_application_error_rejects_too_many_detail_values() -> None:
    with pytest.raises(ValueError, match="too many values"):
        ApplicationError(
            details={"values": list(range(101))},
        )


def test_base_error_has_safe_defaults_and_fresh_details() -> None:
    first, second = ApplicationError(), ApplicationError(details=None)
    assert first.status_code == HTTPStatus.BAD_REQUEST
    assert first.code == "application_error"
    assert first.message == "The request could not be processed."
    assert str(first) == first.message and first.args == (first.message,)
    first.details["reason"] = "safe"
    assert second.details == {}
    first.headers["X-Test"] = "unused"
    assert first.headers == {} and second.headers == {}


@pytest.mark.parametrize("status_code", [True, "404", 404.0, None])
def test_error_rejects_non_integer_status(status_code: object) -> None:
    error_type = type("InvalidStatusError", (ApplicationError,), {"status_code": status_code})
    with pytest.raises(TypeError, match="status_code must be an integer"):
        error_type()


@pytest.mark.parametrize("status_code", [199, 200, 399, 600])
def test_error_rejects_non_error_status(status_code: int) -> None:
    error_type = type("InvalidStatusError", (ApplicationError,), {"status_code": status_code})
    with pytest.raises(ValueError, match="between 400 and 599"):
        error_type()


@pytest.mark.parametrize(
    "overrides", [{"code": "replacement"}, {"message": "replacement"}, {"status_code": 500}]
)
def test_error_metadata_is_not_supplied_at_call_sites(overrides: dict[str, Any]) -> None:
    with pytest.raises(TypeError):
        ApplicationError(**overrides)


def test_details_are_copied_recursively() -> None:
    nested: dict[str, JsonValue] = {"fields": ["email"]}
    first = ApplicationError(details=nested)
    second = ApplicationError(details=nested)
    assert first.details == second.details == nested
    assert first.details is not nested
    assert first.details["fields"] is not nested["fields"]
    assert first.details["fields"] is not second.details["fields"]
