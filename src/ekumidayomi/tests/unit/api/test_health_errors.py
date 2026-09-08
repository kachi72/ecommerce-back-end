"""Readiness failures preserve their safe, structured response contract."""

from typing import Any

import pytest
from starlette.requests import Request

from ekumidayomi.api.errors import handle_application_error
from ekumidayomi.api.health_errors import ServiceNotReadyError
from ekumidayomi.users.errors import IdentityRateLimitExceededError


def test_readiness_error_has_stable_metadata_and_copies_checks() -> None:
    error = ServiceNotReadyError(checks={"postgresql": "failed", "redis": "ok"})
    assert error.status_code == 503
    assert error.code == "service_not_ready"
    assert error.message == "Service is not ready"
    assert error.details == {"checks": {"postgresql": "failed", "redis": "ok"}}


@pytest.mark.parametrize(
    "checks",
    [
        {},
        {"postgresql": "failed"},
        {"postgresql": "private exception", "redis": "ok"},
        {"postgresql": "failed", "redis": "ok", "other": "failed"},
        {"postgresql": "ok", "redis": "ok"},
    ],
)
def test_readiness_details_reject_unknown_or_successful_outcomes(
    checks: dict[str, Any],
) -> None:
    with pytest.raises(ValueError):
        ServiceNotReadyError(checks=checks)


async def test_declared_error_headers_reach_the_http_response() -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "state": {"request_id": "header-contract"},
        }
    )
    response = await handle_application_error(
        request, IdentityRateLimitExceededError(retry_after=7)
    )
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "7"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Request-ID"] == "header-contract"
