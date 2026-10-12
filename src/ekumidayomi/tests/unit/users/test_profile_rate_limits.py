from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from redis.exceptions import RedisError
from starlette.requests import Request

from ekumidayomi.auth.sessions import Actor
from ekumidayomi.core.settings import AppEnvironment, Settings
from ekumidayomi.users import rate_dependencies
from ekumidayomi.users.errors import ProfileRateLimitExceededError
from ekumidayomi.users.model import Role


class RecordingMetrics:
    def __init__(self) -> None:
        self.increments: list[tuple[str, dict[str, str] | None]] = []

    def increment(self, name: str, *, labels: dict[str, str] | None = None) -> None:
        self.increments.append((name, labels))

    def observe(
        self,
        name: str,
        value: float,
        *,
        labels: dict[str, str] | None = None,
    ) -> None:
        return None


def request_for(method: str, route_path: str) -> tuple[Request, RecordingMetrics]:
    application = FastAPI()
    application.state.settings = Settings(
        _env_file=None,
        app_env=AppEnvironment.TEST,
        check_dependencies_on_startup=False,
        secret_key="profile-rate-limit-test-secret",
    )
    application.state.redis = object()
    metrics = RecordingMetrics()
    application.state.metrics = metrics
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "https",
            "path": route_path,
            "raw_path": route_path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 443),
            "app": application,
            "route": SimpleNamespace(path=route_path),
        }
    )
    return request, metrics


def actor() -> Actor:
    return Actor(
        user_id=uuid4(),
        session_id=uuid4(),
        role=Role.CUSTOMER,
        authenticated_at=datetime.now(UTC),
    )


@pytest.mark.parametrize(
    "method,path,expected",
    [
        ("GET", "/api/v1/profile", None),
        ("GET", "/api/v1/profile/addresses", None),
        ("PUT", "/api/v1/profile", ("profile-update", "profile")),
        ("POST", "/api/v1/profile/addresses", ("address-create", "address")),
        (
            "PUT",
            "/api/v1/profile/addresses/{address_id}",
            ("address-update", "address"),
        ),
        (
            "DELETE",
            "/api/v1/profile/addresses/{address_id}",
            ("address-delete", "address"),
        ),
    ],
)
def test_profile_route_classification(
    method: str, path: str, expected: tuple[str, str] | None
) -> None:
    assert rate_dependencies.profile_rate_limit_operation(method, path, "/api/v1") == expected


async def test_profile_limit_returns_stable_retry_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, metrics = request_for("PUT", "/api/v1/profile")
    check = AsyncMock(return_value=7)
    monkeypatch.setattr(rate_dependencies, "sliding_window_retry_after", check)

    with pytest.raises(ProfileRateLimitExceededError) as captured:
        await rate_dependencies.profile_rate_limit(request, actor())

    assert captured.value.details == {"retry_after": 7}
    assert captured.value.headers == {"Retry-After": "7"}
    assert metrics.increments == [
        (
            "profile_rate_limit_rejections_total",
            {"operation": "profile-update"},
        )
    ]


async def test_profile_limit_fails_open_safely_when_redis_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, metrics = request_for("DELETE", "/api/v1/profile/addresses/{address_id}")
    check = AsyncMock(side_effect=RedisError("private connection detail"))
    warning = MagicMock()
    monkeypatch.setattr(rate_dependencies, "sliding_window_retry_after", check)
    monkeypatch.setattr(rate_dependencies.logger, "warning", warning)

    await rate_dependencies.profile_rate_limit(request, actor())

    assert metrics.increments == [
        (
            "profile_rate_limit_backend_errors_total",
            {"operation": "address-delete"},
        )
    ]
    warning.assert_called_once_with(
        "profile_rate_limit_backend_unavailable",
        extra={"rate_limit_operation": "address-delete"},
    )
    assert "private connection detail" not in repr(warning.call_args)
