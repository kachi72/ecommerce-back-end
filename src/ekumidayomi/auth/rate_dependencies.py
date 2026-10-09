"""Versioned identity entry-point limits before password hashing or delivery."""

import json
from typing import Annotated

from fastapi import Depends, Request

from ekumidayomi.auth.dependencies import app_settings, cookie_name, trusted_origin
from ekumidayomi.auth.rate_limits import enforce
from ekumidayomi.auth.settings import AuthSettings
from ekumidayomi.core.dependencies import get_auth_settings
from ekumidayomi.db.dependencies import get_redis
from ekumidayomi.users.errors import AuthenticationRequestTooLargeError, InvalidEmailError
from ekumidayomi.users.repository import normalize_email

_LIMITS = {
    "/auth/login": (30, 10, 300),
    "/auth/register": (20, 3, 600),
    "/auth/register/resend": (20, 3, 600),
    "/auth/register.verify": (30, 5, 600),
    "/auth/password-reset/request": (20, 3, 600),
    "/auth/password-reset/confirm": (30, 5, 600),
    "/auth/reauthenticate": (2, 5, 300),
}


async def identify_rate_limit(
    request: Request, config: Annotated[AuthSettings, Depends(get_auth_settings)]
) -> None:
    settings = app_settings(request)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        trusted_origin(request, config)
    path = request.url.path.removeprefix(settings.api_prefix)
    rule = _LIMITS.get(path)
    if path.startswith("/auth/oidc/"):
        rule = (30, 10, 300)
    if rule is None:
        return None
    ip_limit, account_limit, window = rule
    client_ip = request.client.host if request.client else "unknown"
    redis = get_redis(request)
    secret = settings.secret_key.get_secret_value()
    operation = path.strip("/").replace("/", "-")
    await enforce(
        redis,
        namespace=settings.app_env.value,
        operation=operation + "-ip",
        identity=client_ip,
        secret=secret,
        limit=ip_limit,
        window_seconds=window,
    )
    identity = ""
    if request.method == "POST":
        body = await request.body()
        if len(body) > 16384:
            raise AuthenticationRequestTooLargeError()
        try:
            data = json.loads(body) if body else {}
        except (ValueError, UnicodeDecodeError):
            data = {}
        if isinstance(data, dict):
            email = data.get("email")
            if isinstance(email, str):
                try:
                    identity = normalize_email(email)
                except InvalidEmailError:
                    identity = email.strip().casefold()[:320]
            challenge_id = data.get("challenge_id")
            if not identity and isinstance(challenge_id, str):
                identity = challenge_id[:64]
    if not identity and path == "/auth/reauthenticate":
        identity = request.cookies.get(cookie_name(settings), "")
    if identity:
        await enforce(
            redis,
            namespace=settings.app_env.value,
            operation=operation + "-account",
            identity=identity,
            secret=secret,
            limit=account_limit,
            window_seconds=window,
        )
