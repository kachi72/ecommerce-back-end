"""The shared handler preserves stable rate-limit details and HTTP headers."""

from starlette.requests import Request

from ekumidayomi.api.errors import handle_application_error
from ekumidayomi.users.errors import IdentityRateLimitExceededError


async def test_named_rate_limit_error_sets_retry_after_header() -> None:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/login",
            "headers": [],
            "state": {"request_id": "rate-error-test"},
        }
    )
    response = await handle_application_error(
        request, IdentityRateLimitExceededError(retry_after=7)
    )
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "7"
    assert response.headers["Cache-Control"] == "no-store"
