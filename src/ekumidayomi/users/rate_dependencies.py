"""Resource limits for authenticated profile mutations."""

import logging
from typing import Annotated, cast

from fastapi import Depends, Request
from redis.exceptions import RedisError

from ekumidayomi.auth.dependencies import app_settings, current_actor
from ekumidayomi.auth.sessions import Actor
from ekumidayomi.core.observability import Metrics
from ekumidayomi.core.rate_limits import rate_limit_key, sliding_window_retry_after
from ekumidayomi.db.dependencies import get_redis
from ekumidayomi.users.errors import ProfileRateLimitExceededError

logger = logging.getLogger(__name__)

_OPERATIONS = {
    ("PUT", "/profile"): ("profile-update", "profile"),
    ("POST", "/profile/addresses"): ("address-create", "address"),
    ("PUT", "/profile/addresses/{address_id}"): ("address-update", "address"),
    ("DELETE", "/profile/addresses/{address_id}"): ("address-delete", "address"),
}


def profile_rate_limit_operation(
    method: str, route_path: str, api_prefix: str
) -> tuple[str, str] | None:

    prefix = api_prefix.rstrip("/")
    normalized_path = route_path.removeprefix(prefix) if prefix else route_path
    return _OPERATIONS.get((method.upper(), normalized_path))


async def profile_rate_limit(
    request: Request, actor: Annotated[Actor, Depends(current_actor)]
) -> None:
    """Apply a per-user mutation budget without making Redis authoritative."""

    route = request.scope.get("route")
    route_path = getattr(route, "path", "")
    settings = app_settings(request)
    resolved = profile_rate_limit_operation(request.method, route_path, settings.api_prefix)
    if resolved is None:
        return None
    operation, group = resolved
    config = settings.profile_rate_limits
    limit = config.profile_update_limit if group == "profile" else config.address_mutation_limit
    key = rate_limit_key(
        namespace=settings.app_env.value,
        scope="users",
        operation=operation,
        identity=str(actor.user_id),
        secret=settings.secret_key.get_secret_value(),
    )
    metrics = cast(Metrics, request.app.state.metrics)
    try:
        retry = await sliding_window_retry_after(
            get_redis(request), key=key, limit=limit, window_seconds=config.window_seconds
        )
    except RedisError:
        metrics.increment(
            "profile_rate_limit_backend_errors_total", labels={"operation": operation}
        )
        logger.warning(
            "profile_rate_limit_backend_unavailable", extra={"rate_limit_operation": operation}
        )
        return None
    if retry > 0:
        metrics.increment("profile_rate_limit_rejections_total", labels={"operation": operation})
        raise ProfileRateLimitExceededError(retry_after=retry)
