"""Identity rate dependencies classify requests without exposing identifiers."""

import json
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from starlette.requests import Request

from ekumidayomi.auth import rate_dependencies
from ekumidayomi.auth.settings import AuthSettings
from ekumidayomi.core.settings import AppEnvironment, Settings
from ekumidayomi.users.errors import (
    AuthenticationRequestTooLargeError,
    UntrustedOriginError,
)


def request_for(
    path: str,
    *,
    method: str = "POST",
    body: bytes = b"",
    origin: str = "http://testserver",
    cookie: str | None = None,
    include_client: bool = True,
) -> Request:
    application = FastAPI()
    application.state.settings = Settings(
        _env_file=None,
        app_env=AppEnvironment.TEST,
        check_dependencies_on_startup=False,
        secret_key="identity-rate-limit-test-secret",
    )
    application.state.redis = object()
    headers = [(b"origin", origin.encode())]
    if cookie is not None:
        headers.append((b"cookie", f"ekumidayomi_session={cookie}".encode()))
    delivered = False

    async def receive() -> dict[str, object]:
        nonlocal delivered
        if delivered:
            return {"type": "http.request", "body": b"", "more_body": False}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 1234) if include_client else None,
            "server": ("testserver", 443),
            "app": application,
        },
        receive,
    )


async def test_login_limits_ip_and_normalized_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enforce = AsyncMock()
    monkeypatch.setattr(rate_dependencies, "enforce", enforce)
    request = request_for(
        "/api/v1/auth/login",
        body=json.dumps({"email": " Customer@EXAMPLE.com "}).encode(),
    )

    await rate_dependencies.identify_rate_limit(
        request,
        AuthSettings(allowed_origins=["http://testserver"]),
    )

    assert enforce.await_count == 2
    ip_call, account_call = enforce.await_args_list
    assert ip_call.kwargs["operation"] == "auth-login-ip"
    assert ip_call.kwargs["identity"] == "127.0.0.1"
    assert account_call.kwargs["operation"] == "auth-login-account"
    assert account_call.kwargs["identity"] == "customer@example.com"
    assert account_call.kwargs["limit"] == 10
    assert account_call.kwargs["window_seconds"] == 300


@pytest.mark.parametrize(
    ("path", "body", "expected_identity"),
    [
        (
            "/api/v1/auth/register/verify",
            {"challenge_id": "00000000-0000-4000-8000-000000000001"},
            "00000000-0000-4000-8000-000000000001",
        ),
        (
            "/api/v1/auth/register",
            {"email": " not-an-email "},
            "not-an-email",
        ),
    ],
)
async def test_challenge_and_invalid_email_identifiers_are_bounded(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    body: dict[str, str],
    expected_identity: str,
) -> None:
    enforce = AsyncMock()
    monkeypatch.setattr(rate_dependencies, "enforce", enforce)

    await rate_dependencies.identify_rate_limit(
        request_for(path, body=json.dumps(body).encode()),
        AuthSettings(allowed_origins=["http://testserver"]),
    )

    assert enforce.await_args_list[-1].kwargs["identity"] == expected_identity


async def test_reauthentication_uses_the_session_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enforce = AsyncMock()
    monkeypatch.setattr(rate_dependencies, "enforce", enforce)

    await rate_dependencies.identify_rate_limit(
        request_for(
            "/api/v1/auth/reauthenticate",
            body=b"{}",
            cookie="s" * 43,
        ),
        AuthSettings(allowed_origins=["http://testserver"]),
    )

    assert enforce.await_args_list[-1].kwargs["identity"] == "s" * 43


@pytest.mark.parametrize("body", [b"{", b"[]", b"{}"])
async def test_body_without_an_identity_only_applies_the_ip_limit(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
) -> None:
    enforce = AsyncMock()
    monkeypatch.setattr(rate_dependencies, "enforce", enforce)

    await rate_dependencies.identify_rate_limit(
        request_for("/api/v1/auth/login", body=body, include_client=False),
        AuthSettings(allowed_origins=["http://testserver"]),
    )

    enforce.assert_awaited_once()
    enforce_call = enforce.await_args
    assert enforce_call is not None
    assert enforce_call.kwargs["identity"] == "unknown"


async def test_oidc_paths_use_the_provider_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enforce = AsyncMock()
    monkeypatch.setattr(rate_dependencies, "enforce", enforce)

    await rate_dependencies.identify_rate_limit(
        request_for("/api/v1/auth/oidc/google/start", method="GET"),
        AuthSettings(allowed_origins=["http://testserver"]),
    )

    enforce.assert_awaited_once()
    enforce_call = enforce.await_args
    assert enforce_call is not None
    assert enforce_call.kwargs["limit"] == 30


async def test_unlimited_safe_route_returns_without_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enforce = AsyncMock()
    monkeypatch.setattr(rate_dependencies, "enforce", enforce)

    await rate_dependencies.identify_rate_limit(
        request_for("/api/v1/auth/me", method="GET"),
        AuthSettings(),
    )

    enforce.assert_not_awaited()


async def test_untrusted_origin_is_rejected_before_limiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enforce = AsyncMock()
    monkeypatch.setattr(rate_dependencies, "enforce", enforce)

    with pytest.raises(UntrustedOriginError):
        await rate_dependencies.identify_rate_limit(
            request_for("/api/v1/auth/login", origin="https://evil.test"),
            AuthSettings(allowed_origins=["http://testserver"]),
        )

    enforce.assert_not_awaited()


async def test_oversized_request_stops_before_account_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enforce = AsyncMock()
    monkeypatch.setattr(rate_dependencies, "enforce", enforce)

    with pytest.raises(AuthenticationRequestTooLargeError):
        await rate_dependencies.identify_rate_limit(
            request_for("/api/v1/auth/login", body=b"x" * 16385),
            AuthSettings(allowed_origins=["http://testserver"]),
        )

    enforce.assert_awaited_once()
