"""Tests for stable, privacy-safe API error responses."""

import logging
from uuid import UUID

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, ConfigDict, Field

from ekumidayomi.api.errors import (
    handle_application_error,
    handle_request_validation_error,
    register_error_handlers,
)
from ekumidayomi.core.errors import (
    ApplicationError,
    AuthenticationError,
    ConflictError,
    DependencyUnavailableError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)


class RequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: int = Field(gt=0)
    name: str


ERROR_CASES = [
    (NotFoundError, 404),
    (ConflictError, 409),
    (ForbiddenError, 403),
    (AuthenticationError, 401),
    (ValidationError, 422),
    (RateLimitError, 429),
    (DependencyUnavailableError, 503),
    (ApplicationError, 400),
]


def build_error_app() -> FastAPI:
    application = FastAPI()
    register_error_handlers(application)

    @application.get("/application-error/{case_index}")
    async def application_error(case_index: int) -> None:
        error_type, _ = ERROR_CASES[case_index]
        raise error_type(
            code="stable_failure",
            message="A safe failure occurred",
            details={"field": "quantity"},
        )

    @application.post("/validation")
    async def validation(body: RequestBody) -> RequestBody:
        return body

    @application.get("/unexpected")
    async def unexpected() -> None:
        raise RuntimeError("password=private-value")

    @application.get("/state-request-id")
    async def state_request_id(request: Request) -> None:
        request.state.request_id = "state-request-123"
        raise NotFoundError(code="missing", message="Resource was not found")

    return application


@pytest.mark.asyncio
@pytest.mark.parametrize(("case_index", "case"), enumerate(ERROR_CASES))
async def test_application_error_status_mapping_and_envelope(
    case_index: int,
    case: tuple[type[ApplicationError], int],
) -> None:
    _, expected_status = case
    app = build_error_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            f"/application-error/{case_index}",
            headers={"X-Request-ID": "request-123"},
        )

    assert response.status_code == expected_status
    assert response.headers["x-request-id"] == "request-123"
    assert response.json() == {
        "error": {
            "code": "stable_failure",
            "message": "A safe failure occurred",
            "details": {"field": "quantity"},
            "request_id": "request-123",
        }
    }


@pytest.mark.asyncio
async def test_request_validation_is_deterministic_and_does_not_echo_input() -> None:
    app = build_error_app()
    private_value = "password=not-for-the-response"

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/validation",
            json={
                "quantity": private_value,
                "unexpected": "raw-private-input",
            },
            headers={"X-Request-ID": "validation-456"},
        )

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "request_validation_failed",
            "message": "Request validation failed",
            "details": {
                "fields": [
                    {
                        "path": "body.name",
                        "code": "required",
                        "message": "Field is required",
                    },
                    {
                        "path": "body.quantity",
                        "code": "invalid_type",
                        "message": "Value has an invalid type",
                    },
                    {
                        "path": "body.unexpected",
                        "code": "unexpected_field",
                        "message": "Field is not allowed",
                    },
                ]
            },
            "request_id": "validation-456",
        }
    }
    assert private_value not in response.text
    assert "raw-private-input" not in response.text
    assert "input" not in response.json()["error"]["details"]["fields"][0]


@pytest.mark.asyncio
async def test_validation_paths_replace_unsafe_segments() -> None:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/failure")
    async def failure() -> None:
        from fastapi.exceptions import RequestValidationError

        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("body", "unsafe.segment", -1, True),
                    "msg": "private framework text",
                    "input": "private raw value",
                },
                {
                    "type": "value_error",
                    "loc": "not-a-sequence",
                    "msg": "private framework text",
                    "input": "private raw value",
                },
                {
                    "type": "value_error",
                    "loc": ("body", "items", 0),
                    "msg": "private framework text",
                    "input": "private raw value",
                },
            ]
        )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/failure")

    fields = response.json()["error"]["details"]["fields"]
    assert fields == [
        {
            "path": "body.field.field.field",
            "code": "invalid_value",
            "message": "Value is invalid",
        },
        {
            "path": "body.items.0",
            "code": "invalid_value",
            "message": "Value is invalid",
        },
        {
            "path": "request",
            "code": "invalid_value",
            "message": "Value is invalid",
        },
    ]
    assert "private" not in response.text


@pytest.mark.asyncio
async def test_validation_normalizes_range_errors() -> None:
    app = build_error_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post("/validation", json={"quantity": 0, "name": "item"})

    assert response.json()["error"]["details"]["fields"] == [
        {
            "path": "body.quantity",
            "code": "out_of_range",
            "message": "Value is outside the allowed range",
        }
    ]


@pytest.mark.asyncio
async def test_unexpected_error_is_generic_and_logs_only_safe_context(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = build_error_app()
    caplog.set_level(logging.ERROR, logger="ekumidayomi.api.errors")

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/unexpected?password=query-secret",
            headers={"X-Request-ID": "unexpected-789"},
        )

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "An unexpected error occurred",
            "details": {},
            "request_id": "unexpected-789",
        }
    }
    assert "private-value" not in response.text
    assert "query-secret" not in caplog.text
    assert "private-value" not in caplog.text
    record_context = caplog.records[0].__dict__
    assert record_context["request_id"] == "unexpected-789"
    assert record_context["request_path"] == "/unexpected"
    assert record_context["exception_type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_invalid_request_id_is_replaced() -> None:
    app = build_error_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/application-error/0",
            headers={"X-Request-ID": "invalid request id"},
        )

    generated = response.json()["error"]["request_id"]
    assert UUID(generated)
    assert response.headers["x-request-id"] == generated


@pytest.mark.asyncio
async def test_request_state_id_takes_precedence_over_header() -> None:
    app = build_error_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/state-request-id",
            headers={"X-Request-ID": "header-request-456"},
        )

    assert response.headers["x-request-id"] == "state-request-123"
    assert response.json()["error"]["request_id"] == "state-request-123"


@pytest.mark.asyncio
async def test_handlers_reject_wrong_exception_types() -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "headers": [],
        }
    )

    with pytest.raises(TypeError, match="application error handler"):
        await handle_application_error(request, RuntimeError("wrong"))
    with pytest.raises(TypeError, match="request validation handler"):
        await handle_request_validation_error(request, RuntimeError("wrong"))
