"""HTTP adapter for the stable application error contract."""

from __future__ import annotations

import logging
import re
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ekumidayomi.core.errors import (
    ApplicationError,
    AuthenticationError,
    ConflictError,
    DependencyUnavailableError,
    ForbiddenError,
    JsonValue,
    NotFoundError,
    RateLimitError,
    ValidationError,
)

logger = logging.getLogger(__name__)

ERROR_STATUS_BY_TYPE: dict[type[ApplicationError], int] = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ConflictError: status.HTTP_409_CONFLICT,
    ForbiddenError: status.HTTP_403_FORBIDDEN,
    AuthenticationError: status.HTTP_401_UNAUTHORIZED,
    ValidationError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    RateLimitError: status.HTTP_429_TOO_MANY_REQUESTS,
    DependencyUnavailableError: status.HTTP_503_SERVICE_UNAVAILABLE,
    ApplicationError: status.HTTP_400_BAD_REQUEST,
}

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_FIELD_SEGMENT_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


class ErrorDetail(BaseModel):
    """Stable details nested inside every API error response."""

    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    details: dict[str, JsonValue] = Field(default_factory=dict)
    request_id: str


class ErrorEnvelope(BaseModel):
    """The only application-owned API error envelope."""

    model_config = ConfigDict(frozen=True)

    error: ErrorDetail


def register_error_handlers(application: FastAPI) -> None:
    """Register application, request-validation, and unexpected handlers."""

    application.add_exception_handler(ApplicationError, handle_application_error)
    application.add_exception_handler(RequestValidationError, handle_request_validation_error)
    application.add_exception_handler(Exception, handle_unexpected_error)


async def handle_application_error(request: Request, error: Exception) -> JSONResponse:
    """Translate an HTTP-neutral application error at the API boundary."""

    if not isinstance(error, ApplicationError):
        raise TypeError("application error handler received an unsupported exception")
    status_code = next(
        (
            mapped_status
            for error_type, mapped_status in ERROR_STATUS_BY_TYPE.items()
            if isinstance(error, error_type)
        ),
        status.HTTP_400_BAD_REQUEST,
    )
    return _error_response(
        request=request,
        status_code=status_code,
        code=error.code,
        message=error.message,
        details=error.details,
    )


async def handle_request_validation_error(request: Request, error: Exception) -> JSONResponse:
    """Normalize framework validation failures without echoing rejected input."""

    if not isinstance(error, RequestValidationError):
        raise TypeError("request validation handler received an unsupported exception")
    issues = sorted(
        (_normalize_validation_issue(item) for item in error.errors()),
        key=lambda item: (str(item["path"]), str(item["code"])),
    )
    return _error_response(
        request=request,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="request_validation_failed",
        message="Request validation failed",
        details={"fields": issues},
    )


async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
    """Log safe correlation context and hide private exception information."""

    request_id = _request_id(request)
    logger.error(
        "Unhandled application exception",
        extra={
            "request_id": request_id,
            "method": request.method,
            "exception_type": type(error).__name__,
        },
    )
    return _error_response(
        request=request,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="internal_error",
        message="An unexpected error occurred",
        details={},
        request_id=request_id,
    )


def _error_response(
    *,
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, JsonValue],
    request_id: str | None = None,
) -> JSONResponse:
    resolved_request_id = request_id or _request_id(request)
    envelope = ErrorEnvelope(
        error=ErrorDetail(
            code=code,
            message=message,
            details=details,
            request_id=resolved_request_id,
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=envelope.model_dump(mode="json"),
        headers={"X-Request-ID": resolved_request_id},
    )


def _request_id(request: Request) -> str:
    state_request_id = getattr(request.state, "request_id", None)
    if isinstance(state_request_id, str) and _REQUEST_ID_PATTERN.fullmatch(state_request_id):
        return state_request_id
    header_request_id = request.headers.get("X-Request-ID")
    if header_request_id is not None and _REQUEST_ID_PATTERN.fullmatch(header_request_id):
        return header_request_id
    return str(uuid4())


def _normalize_validation_issue(item: dict[str, Any]) -> dict[str, JsonValue]:
    error_type = str(item.get("type", "invalid"))
    code, message = _validation_code_and_message(error_type)
    return {
        "path": _validation_path(item.get("loc", ())),
        "code": code,
        "message": message,
    }


def _validation_path(location: object) -> str:
    if not isinstance(location, list | tuple):
        return "request"
    segments: list[str] = []
    for segment in location:
        if isinstance(segment, int) and not isinstance(segment, bool) and segment >= 0:
            segments.append(str(segment))
        elif isinstance(segment, str) and _FIELD_SEGMENT_PATTERN.fullmatch(segment):
            segments.append(segment)
        else:
            segments.append("field")
    return ".".join(segments) or "request"


def _validation_code_and_message(error_type: str) -> tuple[str, str]:
    if error_type == "missing":
        return "required", "Field is required"
    if error_type == "extra_forbidden":
        return "unexpected_field", "Field is not allowed"
    if error_type.endswith("_parsing") or error_type.endswith("_type"):
        return "invalid_type", "Value has an invalid type"
    if any(part in error_type for part in ("greater_than", "less_than", "too_long", "too_short")):
        return "out_of_range", "Value is outside the allowed range"
    return "invalid_value", "Value is invalid"
