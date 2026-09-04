"""API-level evidence for shared platform safety contracts."""

import pytest
from fastapi import APIRouter
from httpx import ASGITransport, AsyncClient

from ekumidayomi.core.application import create_app
from ekumidayomi.core.settings import Settings

pytestmark = pytest.mark.unit


async def test_unexpected_api_failure_uses_safe_envelope_and_request_id() -> None:
    application = create_app(
        Settings(
            _env_file=None,
            check_dependencies_on_startup=False,
            trust_incoming_request_ids=True,
        )
    )
    router = APIRouter()

    @router.get("/platform-failure")
    async def fail() -> None:
        raise RuntimeError("secret internal detail")

    application.include_router(router)
    async with AsyncClient(
        transport=ASGITransport(app=application, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/platform-failure",
            headers={"X-Request-ID": "platform-test"},
        )

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "platform-test"
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "An unexpected error occurred",
            "details": {},
            "request_id": "platform-test",
        }
    }
    assert "secret internal detail" not in response.text
