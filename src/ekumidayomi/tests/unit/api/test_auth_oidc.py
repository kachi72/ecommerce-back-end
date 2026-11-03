"""OIDC routes expose only enabled providers and stable error envelopes."""

from uuid import UUID

from fastapi.routing import iter_route_contexts
from httpx import ASGITransport, AsyncClient

from ekumidayomi.auth.rate_dependencies import identify_rate_limit
from ekumidayomi.core.application import create_app
from ekumidayomi.core.settings import Settings


def oidc_test_settings() -> Settings:
    return Settings(
        _env_file=None,
        check_dependencies_on_startup=False,
        allowed_hosts=["testserver"],
        auth={"allowed_origins": ["http://testserver"]},
    )


def test_oidc_routes_are_registered_under_the_versioned_auth_prefix() -> None:
    application = create_app(oidc_test_settings())
    paths = {
        route.path
        for route in iter_route_contexts(application.routes)
        if route.path is not None and "/auth/oidc" in route.path
    }

    assert paths == {
        "/api/v1/auth/oidc/{provider}",
        "/api/v1/auth/oidc/{provider}/callback",
        "/api/v1/auth/oidc/{provider}/link",
        "/api/v1/auth/oidc/{provider}/reauthenticate",
        "/api/v1/auth/oidc/{provider}/start",
        "/api/v1/auth/oidc/identities",
    }


async def test_disabled_provider_start_uses_generic_external_login_error() -> None:
    application = create_app(oidc_test_settings())
    application.dependency_overrides[identify_rate_limit] = lambda: None

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://testserver",
        headers={"Origin": "http://testserver", "X-Request-ID": "disabled-provider"},
    ) as client:
        response = await client.post("/api/v1/auth/oidc/google/start")

    assert response.status_code == 401
    error = response.json()["error"]
    assert UUID(error.pop("request_id"))
    assert error == {
        "code": "external_login_failed",
        "message": "External sign-in could not be completed.",
        "details": {},
    }
