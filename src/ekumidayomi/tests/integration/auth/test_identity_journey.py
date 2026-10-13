"""Exercise the customer identity journey through the in-process ASGI app."""

from collections.abc import AsyncIterator
from uuid import UUID

import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from ekumidayomi.auth.challenge_model import EmailChallenge
from ekumidayomi.auth.challenges import derive_code
from ekumidayomi.auth.rate_dependencies import identify_rate_limit
from ekumidayomi.auth.settings import AuthSettings
from ekumidayomi.core.application import create_app
from ekumidayomi.core.settings import Settings
from ekumidayomi.db.dependencies import get_redis, get_unit_of_work
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users.rate_dependencies import profile_rate_limit


@pytest.fixture
async def identity_client(
    identity_uow: UnitOfWork,
    fake_redis: fakeredis.aioredis.FakeRedis,
    test_settings: Settings,
) -> AsyncIterator[AsyncClient]:
    auth_settings = AuthSettings(
        allowed_origins=["http://testserver"],
        challenge_keys={"v1": SecretStr("k" * 32)},
    )
    settings = Settings.model_validate(
        {
            **test_settings.model_dump(),
            "auth": auth_settings,
            "cors_origins": ["http://testserver"],
        }
    )
    application = create_app(settings)
    application.state.redis = fake_redis

    async def override_uow() -> AsyncIterator[UnitOfWork]:
        yield identity_uow

    async def no_rate_limit() -> None:
        return None

    application.dependency_overrides[get_unit_of_work] = override_uow
    application.dependency_overrides[get_redis] = lambda: fake_redis
    application.dependency_overrides[identify_rate_limit] = no_rate_limit
    application.dependency_overrides[profile_rate_limit] = no_rate_limit
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    ) as client:
        yield client


@pytest.mark.critical_flow
async def test_customer_identity_journey(
    identity_client: AsyncClient,
    identity_uow: UnitOfWork,
) -> None:
    password = "quiet meadows beyond the river"
    initiated = await identity_client.post(
        "/api/v1/auth/register",
        json={"email": "journey@example.com"},
    )
    assert initiated.status_code == 202
    challenge_id = UUID(initiated.json()["challenge_id"])
    challenge = await identity_uow.session.get(EmailChallenge, challenge_id)
    assert challenge is not None
    settings = AuthSettings(challenge_keys={"v1": SecretStr("k" * 32)})

    verified = await identity_client.post(
        "/api/v1/auth/register/verify",
        json={
            "challenge_id": str(challenge_id),
            "code": derive_code(challenge, settings),
            "password": password,
        },
    )
    assert verified.status_code == 204

    signed_in = await identity_client.post(
        "/api/v1/auth/login",
        json={"email": "journey@example.com", "password": password},
    )
    assert signed_in.status_code == 204
    session_cookie = identity_client.cookies.get("ekumidayomi_session")
    assert session_cookie is not None

    me = await identity_client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "journey@example.com"
    assert (await identity_client.get("/api/v1/admin/users")).status_code == 403

    profile = await identity_client.put(
        "/api/v1/profile",
        json={"display_name": "Ẹkúmidáyọ̀mí"},
    )
    assert profile.status_code == 200
    assert profile.json()["display_name"] == "Ẹkúmidáyọ̀mí"

    denied = await identity_client.put(
        "/api/v1/profile",
        json={"display_name": "No change"},
        headers={"Origin": "https://evil.test"},
    )
    assert denied.status_code == 403

    assert (await identity_client.post("/api/v1/auth/logout")).status_code == 204
    logged_out = await identity_client.get(
        "/api/v1/auth/me",
        headers={"Cookie": f"ekumidayomi_session={session_cookie}"},
    )
    assert logged_out.status_code == 401
