"""Explicit local permissions; provider claims never participate."""

from enum import StrEnum

from ekumidayomi.auth.model import AuthSession
from ekumidayomi.auth.sessions import Actor
from ekumidayomi.core.types import utc_now
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users.errors import (
    AuthenticationRequiredError,
    PermissionDeniedError,
    ReauthenticationRequiredError,
)
from ekumidayomi.users.model import Role, User
from ekumidayomi.users.repository import find_user_by_id


class Permission(StrEnum):
    PROFILE_WRITE = "profile_write"
    USERS_READ = "users_read"
    USERS_MANAGE = "users_manage"
    AUDIT_READ = "audit_read"


_PERMISSIONS = {
    Role.CUSTOMER: frozenset({Permission.PROFILE_WRITE}),
    Role.ADMIN: frozenset(Permission),
}


async def authorize(
    uow: UnitOfWork,
    actor: Actor,
    permission: Permission,
    *,
    recent_seconds: int | None = None,
    lock: bool = False,
) -> User:
    user = await find_user_by_id(uow.session, actor.user_id, lock=lock)
    session = await uow.session.get(AuthSession, actor.session_id, populate_existing=True)
    if (
        user is None
        or not user.is_active
        or user.email_verified_at is None
        or session is None
        or session.user_id != user.id
        or session.revoked_at is not None
        or session.expires_at <= utc_now()
    ):
        raise AuthenticationRequiredError()
    try:
        role = Role(user.role)
    except ValueError:
        raise PermissionDeniedError() from None
    if permission not in _PERMISSIONS[role]:
        raise PermissionDeniedError()
    if (
        recent_seconds is not None
        and (utc_now() - session.authenticated_at).total_seconds() > recent_seconds
    ):
        raise ReauthenticationRequiredError()
    return user
