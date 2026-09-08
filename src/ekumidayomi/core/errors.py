"""Dependency-free application error contracts."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from http import HTTPStatus
from typing import ClassVar

type JsonValue = bool | int | float | str | Sequence[JsonValue] | Mapping[str, JsonValue] | None

_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_UNSAFE_DETAIL_KEY_PARTS = frozenset(
    {
        "authorization",
        "body",
        "connection",
        "cookie",
        "credential",
        "password",
        "payload",
        "raw",
        "secret",
        "token",
    }
)
_MAX_DETAIL_DEPTH = 6
_MAX_DETAIL_ITEMS = 100
_MAX_DETAIL_STRING_LENGTH = 1_000


class ApplicationError(Exception):
    """A client-safe failure whose subclass owns its public error contract."""

    status_code: ClassVar[int] = HTTPStatus.BAD_REQUEST
    code: ClassVar[str] = "application_error"
    message: ClassVar[str] = "The request could not be processed."

    def __init__(self, *, details: dict[str, JsonValue] | None = None) -> None:
        if isinstance(self.status_code, bool) or not isinstance(self.status_code, int):
            raise TypeError("error status_code must be an integer")
        if not 400 <= self.status_code <= 599:
            raise ValueError("error status_code must be between 400 and 599")
        if not isinstance(self.code, str) or _CODE_PATTERN.fullmatch(self.code) is None:
            raise ValueError("error code must use lowercase snake case")
        if not isinstance(self.message, str):
            raise TypeError("error message must be a string")
        if (
            not self.message
            or len(self.message) > 500
            or any(character in self.message for character in "\r\n\x00")
        ):
            raise ValueError("error message must be a single safe line of at most 500 characters")
        if details is not None and not isinstance(details, dict):
            raise TypeError("error details must be a dictionary")

        self.details = _normalize_details(details if details is not None else {})
        super().__init__(self.message)

    @property
    def headers(self) -> dict[str, str]:
        """Return fresh response headers; structured errors may override this."""
        return {}


class NotFoundError(ApplicationError):
    """A requested resource does not exist or is not visible to the actor."""

    status_code = HTTPStatus.NOT_FOUND
    code = "not_found"
    message = "The requested resource was not found."


class ConflictError(ApplicationError):
    """The request conflicts with current durable state."""

    status_code = HTTPStatus.CONFLICT
    code = "conflict"
    message = "The request conflicts with the current state."


class ForbiddenError(ApplicationError):
    """The authenticated actor is not allowed to perform the operation."""

    status_code = HTTPStatus.FORBIDDEN
    code = "permission_denied"
    message = "This operation is not permitted."


class AuthenticationError(ApplicationError):
    """Authentication is absent or invalid."""

    status_code = HTTPStatus.UNAUTHORIZED
    code = "authentication_required"
    message = "Authentication is required."


class ValidationError(ApplicationError):
    """Application-level input or state validation failed."""

    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "validation_failed"
    message = "The request is invalid."


class RateLimitError(ApplicationError):
    """The caller exceeded an operation-specific limit."""

    status_code = HTTPStatus.TOO_MANY_REQUESTS
    code = "rate_limit_exceeded"
    message = "Too many attempts. Please try again later."


class DependencyUnavailableError(ApplicationError):
    """A required external dependency is temporarily unavailable."""

    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    code = "dependency_unavailable"
    message = "A required service is temporarily unavailable."


def _normalize_details(details: Mapping[str, object]) -> dict[str, JsonValue]:
    budget = [_MAX_DETAIL_ITEMS]
    return {
        _validate_detail_key(key): _normalize_json_value(value, depth=1, budget=budget)
        for key, value in details.items()
    }


def _normalize_json_value(value: object, *, depth: int, budget: list[int]) -> JsonValue:
    if depth > _MAX_DETAIL_DEPTH:
        raise ValueError("error details exceed the maximum nesting depth")
    budget[0] -= 1
    if budget[0] < 0:
        raise ValueError("error details contain too many values")

    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("error details must contain finite numbers")
        return value
    if isinstance(value, str):
        if len(value) > _MAX_DETAIL_STRING_LENGTH:
            raise ValueError("error detail strings must not exceed 1000 characters")
        return value
    if isinstance(value, list | tuple):
        return [_normalize_json_value(item, depth=depth + 1, budget=budget) for item in value]
    if isinstance(value, dict):
        return {
            _validate_detail_key(key): _normalize_json_value(
                item,
                depth=depth + 1,
                budget=budget,
            )
            for key, item in value.items()
        }
    raise TypeError("error details must contain only JSON-safe values")


def _validate_detail_key(key: object) -> str:
    if not isinstance(key, str):
        raise TypeError("error detail keys must be strings")
    normalized = key.casefold().replace("-", "_")
    if any(part in normalized for part in _UNSAFE_DETAIL_KEY_PARTS):
        raise ValueError("error details contain a sensitive key")
    return key
