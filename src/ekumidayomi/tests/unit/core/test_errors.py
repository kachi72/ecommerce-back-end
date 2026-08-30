"""Tests for dependency-free application error contracts."""

import math

import pytest

from ekumidayomi.core.errors import ApplicationError, JsonValue, NotFoundError


def test_application_error_preserves_safe_contract_values() -> None:
    details: dict[str, JsonValue] = {
        "field": "email",
        "reasons": ("required", 2),
        "ratio": 1.5,
        "retry": False,
    }

    error = NotFoundError(
        code="customer_not_found",
        message="Customer was not found",
        details=details,
    )

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
        ApplicationError(code=code, message="Safe message")


def test_application_error_rejects_non_string_code() -> None:
    with pytest.raises(ValueError, match="lowercase snake case"):
        ApplicationError(code=123, message="Safe message")  # type: ignore[arg-type]


@pytest.mark.parametrize("message", ["", "first\nsecond", "nul\x00byte", "x" * 501])
def test_application_error_rejects_unsafe_messages(message: str) -> None:
    with pytest.raises(ValueError, match="single safe line"):
        ApplicationError(code="invalid_request", message=message)


def test_application_error_rejects_non_string_message() -> None:
    with pytest.raises(TypeError, match="must be a string"):
        ApplicationError(code="invalid_request", message=123)  # type: ignore[arg-type]


def test_application_error_rejects_non_dictionary_details() -> None:
    with pytest.raises(TypeError, match="must be a dictionary"):
        ApplicationError(
            code="invalid_request",
            message="Safe message",
            details=[],  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "key",
    ["password", "access_token", "raw_input", "request_body", "cookie_value", "credential"],
)
def test_application_error_rejects_sensitive_detail_keys(key: str) -> None:
    with pytest.raises(ValueError, match="sensitive key"):
        ApplicationError(
            code="invalid_request",
            message="Safe message",
            details={key: "must-not-leak"},
        )


def test_application_error_rejects_non_string_detail_keys() -> None:
    with pytest.raises(TypeError, match="keys must be strings"):
        ApplicationError(
            code="invalid_request",
            message="Safe message",
            details={1: "value"},  # type: ignore[dict-item]
        )


@pytest.mark.parametrize("value", [object(), {1, 2}])
def test_application_error_rejects_non_json_values(value: object) -> None:
    with pytest.raises(TypeError, match="JSON-safe"):
        ApplicationError(
            code="invalid_request",
            message="Safe message",
            details={"value": value},  # type: ignore[dict-item]
        )


@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan])
def test_application_error_rejects_non_finite_numbers(value: float) -> None:
    with pytest.raises(ValueError, match="finite numbers"):
        ApplicationError(
            code="invalid_request",
            message="Safe message",
            details={"value": value},
        )


def test_application_error_rejects_oversized_string() -> None:
    with pytest.raises(ValueError, match="1000 characters"):
        ApplicationError(
            code="invalid_request",
            message="Safe message",
            details={"value": "x" * 1_001},
        )


def test_application_error_rejects_excessive_depth() -> None:
    value: object = "deep"
    for _ in range(7):
        value = [value]

    with pytest.raises(ValueError, match="nesting depth"):
        ApplicationError(
            code="invalid_request",
            message="Safe message",
            details={"value": value},  # type: ignore[dict-item]
        )


def test_application_error_rejects_too_many_detail_values() -> None:
    with pytest.raises(ValueError, match="too many values"):
        ApplicationError(
            code="invalid_request",
            message="Safe message",
            details={"values": list(range(101))},
        )
