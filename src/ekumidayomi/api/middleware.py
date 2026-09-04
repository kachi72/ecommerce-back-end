"""Cross-cutting HTTP middleware."""

import logging
import re
from time import perf_counter
from uuid import uuid4

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from ekumidayomi.core.observability import Metrics, Tracer, bind_request_id, reset_request_id

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

logger = logging.getLogger("ekumidayomi.http")


class RequestObservabilityMiddleware(BaseHTTPMiddleware):
    """Correlate, time, log and measure an HTTP request safely."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        metrics: Metrics,
        tracer: Tracer,
        trust_incoming_request_ids: bool,
    ) -> None:
        super().__init__(app)
        self._metrics = metrics
        self.__tracer = tracer
        self._trust_incoming_request_ids = trust_incoming_request_ids

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = self._request_id(request)
        request.state.request_id = request_id
        token = bind_request_id(request_id)
        started = perf_counter()
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            duration_seconds = perf_counter() - started
            route = request.scope.get("route")
            route_path = getattr(route, "path", None)
            route_template = route_path if isinstance(route_path, str) else "unmatched"
            outcome = self._outcome(status_code)
            labels = {
                "method": request.method,
                "route": route_template,
                "status_code": str(status_code),
            }

            self._metrics.increment("http_requests_total", labels=labels)
            self._metrics.observe("http_request_duration_seconds", duration_seconds, labels=labels)
            self.__tracer.annotate(
                "http.request",
                attributes={
                    "http.request.method": request.method,
                    "http.route": route_template,
                    "http.response.status_code": status_code,
                    "outcome": outcome,
                },
            )
            logger.info(
                "request_completed",
                extra={
                    "method": request.method,
                    "route": route_template,
                    "status_code": status_code,
                    "duration_ms": round(duration_seconds * 1000, 3),
                    "outcome": outcome,
                },
            )
            reset_request_id(token)

    def _request_id(self, request: Request) -> str:
        supplied = request.headers.get(REQUEST_ID_HEADER)
        if (
            self._trust_incoming_request_ids
            and supplied is not None
            and _REQUEST_ID_PATTERN.fullmatch(supplied)
        ):
            return supplied
        return str(uuid4())

    @staticmethod
    def _outcome(status_code: int) -> str:
        if status_code < 400:
            return "success"
        if status_code < 500:
            return "client_error"
        return "server_error"
