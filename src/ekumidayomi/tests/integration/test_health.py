"""Application health integration tests."""

from typing import Literal

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


class UnavailableDatabase:
    """Dependency fake that reports a safe PostgreSQL outage."""

    async def check_connection(self) -> None:
        raise RuntimeError("private PostgreSQL detail")


class UnavailableRedis:
    """Dependency fake that reports a safe Redis outage."""

    async def ping(self) -> None:
        raise RuntimeError("private Redis detail")


async def test_unique_schema_supports_commits(database_session: AsyncSession) -> None:
    """Exercise the schema fixture through its public session behavior."""
    schema = await database_session.scalar(text("SELECT current_schema()"))
    assert isinstance(schema, str)
    assert schema.startswith("test_")
    await database_session.execute(
        text("CREATE TABLE harness_probe (id integer PRIMARY KEY, value text NOT NULL)")
    )
    await database_session.execute(
        text("INSERT INTO harness_probe (id, value) VALUES (1, 'committed')")
    )
    await database_session.commit()

    value = await database_session.scalar(text("SELECT value FROM harness_probe WHERE id = 1"))

    assert value == "committed"


async def test_liveness(api_client: AsyncClient) -> None:
    response = await api_client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readiness(api_client: AsyncClient) -> None:
    response = await api_client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"postgresql": "ok", "redis": "ok"},
    }


@pytest.mark.parametrize("failed_dependency", ["postgresql", "redis"])
async def test_readiness_failure_is_safe(
    failed_dependency: Literal["postgresql", "redis"],
    test_app: FastAPI,
    api_client: AsyncClient,
) -> None:
    if failed_dependency == "postgresql":
        test_app.state.database = UnavailableDatabase()
    else:
        test_app.state.redis = UnavailableRedis()

    response = await api_client.get("/health/ready")

    expected_checks = {"postgresql": "ok", "redis": "ok"}
    expected_checks[failed_dependency] = "failed"
    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "service_not_ready",
            "message": "Service is not ready",
            "details": {"checks": expected_checks},
            "request_id": response.headers["x-request-id"],
        }
    }
    assert "private" not in response.text
