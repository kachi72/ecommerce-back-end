"""Service health endpoints."""

from typing import Literal, cast

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from redis.asyncio import Redis

from ekumidayomi.core.redis import check_redis_connection
from ekumidayomi.db.session import Database

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    """Liveness response returned while the process can serve requests."""

    status: Literal["ok"]


class ReadinessResponse(BaseModel):
    """Readiness response returned when every required dependency is available."""

    status: Literal["ok"]
    checks: dict[str, Literal["ok"]]


@router.get("/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    """Report process liveness without querying external dependencies."""
    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadinessResponse)
async def ready(request: Request) -> ReadinessResponse:
    """Report whether PostgreSQL and Redis can currently serve requests."""
    database = cast(Database, request.app.state.database)
    redis = cast(Redis, request.app.state.redis)
    checks: dict[str, Literal["ok", "failed"]] = {}

    try:
        await database.check_connection()
        checks["postgresql"] = "ok"
    except Exception:
        checks["postgresql"] = "failed"

    try:
        await check_redis_connection(redis)
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "failed"

    if "failed" in checks.values():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "service_not_ready", "checks": checks},
        )

    return ReadinessResponse(
        status="ok",
        checks=cast(dict[str, Literal["ok"]], checks),
    )
