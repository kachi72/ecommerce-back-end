"""Request correlation, metrics, and tracing tests."""

import asyncio
import inspect
from collections.abc import Mapping
from typing import cast
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from ekumidayomi.api.middleware import (
    REQUEST_ID_HEADER,
    RequestObservabilityMiddleware,
)
from ekumidayomi.core import application as application_module
from ekumidayomi.core.application import create_app
from ekumidayomi.core.observability import (
    Metrics,
    NoOpMetrics,
    NoOpTracer,
    Tracer,
    request_id_context,
)
from ekumidayomi.core.settings import Settings


class RecordingMetrics:
    """Capture metric calls without using a provider SDK."""

    def __init__(self) -> None:
        self.increments: list[tuple[str, dict[str, str]]] = []
        self.observations: list[tuple[str, float, dict[str, str]]] = []

    def increment(
        self,
        name: str,
        *,
        labels: Mapping[str, str] | None = None,
    ) -> None:
        self.increments.append((name, dict(labels or {})))

    def observe(
        self,
        name: str,
        value: float,
        *,
        labels: Mapping[str, str] | None = None,
    ) -> None:
        self.observations.append((name, value, dict(labels or {})))


class RecordingTracer:
    """Capture trace annotations without using a provider SDK."""

    def __init__(self) -> None:
        self.annotations: list[tuple[str, dict[str, bool | float | int | str]]] = []

    def annotate(
        self,
        name: str,
        *,
        attributes: Mapping[str, bool | float | int | str] | None = None,
    ) -> None:
        self.annotations.append((name, dict(attributes or {})))


def build_app(
    *,
    metrics: RecordingMetrics,
    tracer: RecordingTracer,
    trust_incoming_request_ids: bool,
) -> FastAPI:
    """Build a minimal app around the real observability middleware."""
    application = FastAPI()

    @application.get("/products/{product_id}")
    async def product(product_id: str, request: Request) -> dict[str, str | None]:
        await asyncio.sleep(0)
        return {
            "product_id": product_id,
            "request_id": request_id_context.get(),
            "state_request_id": cast(str, request.state.request_id),
        }

    @application.get("/failure")
    async def failure() -> None:
        raise RuntimeError("password=must-not-be-exposed")

    @application.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception) -> JSONResponse:
        del error
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error"},
            headers={REQUEST_ID_HEADER: cast(str, request.state.request_id)},
        )

    application.add_middleware(
        RequestObservabilityMiddleware,
        metrics=metrics,
        tracer=tracer,
        trust_incoming_request_ids=trust_incoming_request_ids,
    )
    return application


def test_observability_protocol_methods_are_abstract() -> None:
    assert inspect.isabstract(Metrics)
    assert inspect.isabstract(Tracer)
    assert inspect.getattr_static(Metrics.increment, "__isabstractmethod__") is True
    assert inspect.getattr_static(Metrics.observe, "__isabstractmethod__") is True
    assert inspect.getattr_static(Tracer.annotate, "__isabstractmethod__") is True


def test_noop_adapters_satisfy_the_contract_without_side_effects() -> None:
    metrics = NoOpMetrics()
    tracer = NoOpTracer()

    metrics.increment("requests", labels={"route": "/health/live"})
    metrics.observe("latency", 0.01, labels={"route": "/health/live"})
    tracer.annotate("http.request", attributes={"outcome": "success"})


@pytest.mark.asyncio
async def test_trusted_request_id_is_bound_returned_and_cleaned_up() -> None:
    metrics = RecordingMetrics()
    tracer = RecordingTracer()
    application = build_app(
        metrics=metrics,
        tracer=tracer,
        trust_incoming_request_ids=True,
    )

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/products/product-1",
            headers={REQUEST_ID_HEADER: "request-123"},
        )

    assert response.headers[REQUEST_ID_HEADER] == "request-123"
    assert response.json()["request_id"] == "request-123"
    assert response.json()["state_request_id"] == "request-123"
    assert request_id_context.get() is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("trust_incoming_request_ids", "supplied"),
    [
        (False, "valid-but-untrusted"),
        (True, "contains spaces"),
        (True, "x" * 129),
    ],
)
async def test_untrusted_or_invalid_request_ids_are_replaced(
    trust_incoming_request_ids: bool,
    supplied: str,
) -> None:
    application = build_app(
        metrics=RecordingMetrics(),
        tracer=RecordingTracer(),
        trust_incoming_request_ids=trust_incoming_request_ids,
    )

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/products/product-1",
            headers={REQUEST_ID_HEADER: supplied},
        )

    generated = response.headers[REQUEST_ID_HEADER]
    assert generated != supplied
    assert str(UUID(generated)) == generated
    assert request_id_context.get() is None


@pytest.mark.asyncio
async def test_metrics_and_traces_use_route_templates_not_raw_identifiers() -> None:
    metrics = RecordingMetrics()
    tracer = RecordingTracer()
    application = build_app(
        metrics=metrics,
        tracer=tracer,
        trust_incoming_request_ids=False,
    )

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/products/private-product-123")

    labels = {
        "method": "GET",
        "route": "/products/{product_id}",
        "status_code": "200",
    }
    assert response.status_code == 200
    assert metrics.increments == [("http_requests_total", labels)]
    assert metrics.observations[0][0] == "http_request_duration_seconds"
    assert metrics.observations[0][1] >= 0
    assert metrics.observations[0][2] == labels
    assert tracer.annotations == [
        (
            "http.request",
            {
                "http.request.method": "GET",
                "http.route": "/products/{product_id}",
                "http.response.status_code": 200,
                "outcome": "success",
            },
        )
    ]
    assert "private-product-123" not in repr(metrics.increments)
    assert "private-product-123" not in repr(tracer.annotations)


@pytest.mark.asyncio
async def test_error_path_is_correlated_measured_and_cleans_context() -> None:
    metrics = RecordingMetrics()
    tracer = RecordingTracer()
    application = build_app(
        metrics=metrics,
        tracer=tracer,
        trust_incoming_request_ids=True,
    )

    async with AsyncClient(
        transport=ASGITransport(app=application, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/failure",
            headers={REQUEST_ID_HEADER: "failure-123"},
        )

    assert response.status_code == 500
    assert response.headers[REQUEST_ID_HEADER] == "failure-123"
    assert metrics.increments == [
        (
            "http_requests_total",
            {
                "method": "GET",
                "route": "/failure",
                "status_code": "500",
            },
        )
    ]
    assert tracer.annotations[0][1]["outcome"] == "server_error"
    assert request_id_context.get() is None


@pytest.mark.asyncio
async def test_concurrent_requests_keep_request_context_isolated() -> None:
    application = build_app(
        metrics=RecordingMetrics(),
        tracer=RecordingTracer(),
        trust_incoming_request_ids=True,
    )

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        first, second = await asyncio.gather(
            client.get(
                "/products/first",
                headers={REQUEST_ID_HEADER: "request-first"},
            ),
            client.get(
                "/products/second",
                headers={REQUEST_ID_HEADER: "request-second"},
            ),
        )

    assert first.json()["request_id"] == "request-first"
    assert second.json()["request_id"] == "request-second"
    assert request_id_context.get() is None


def test_application_factory_wires_noop_adapters_and_outermost_middleware(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_logging_mock = MagicMock()
    monkeypatch.setattr(
        application_module,
        "configure_logging",
        configure_logging_mock,
    )
    application = create_app(Settings(_env_file=None, check_dependencies_on_startup=False))

    assert isinstance(application.state.metrics, NoOpMetrics)
    assert isinstance(application.state.tracer, NoOpTracer)
    assert cast(object, application.user_middleware[0].cls) is RequestObservabilityMiddleware
    configure_logging_mock.assert_called_once_with(
        service_name="ekumidayomi-api",
        environment="development",
        level="INFO",
        output_format="json",
    )
