"""Admin membership changes share one durable serialization boundary."""

from uuid import UUID

import sqlalchemy as sa

from ekumidayomi.audit.model import ActorKind, AuditOutcome
from ekumidayomi.audit.service import AuditActor, record
from ekumidayomi.auth.permissions import Permission, authorize
from ekumidayomi.auth.sessions import Actor, SessionService
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users.errors import LastActiveAdminError, UnverifiedAdminError, UserNotFoundError
from ekumidayomi.users.model import Role, User
from ekumidayomi.users.repository import find_user_by_id

ADMIN_MEMBERSHIP_LOCK = 2407001


async def lock_membership(uow: UnitOfWork) -> None:
    await uow.session.execute(
        sa.text("SELECT pg_advisory_xact_lock(:key)"), {"key": ADMIN_MEMBERSHIP_LOCK}
    )


async def change_access(
    uow: UnitOfWork,
    sessions: SessionService,
    *,
    actor: Actor,
    target_id: UUID,
    role: Role | None,
    is_active: bool | None,
    correlation_id: str,
) -> None:
    await lock_membership(uow)
    await authorize(
        uow,
        actor,
        Permission.USERS_MANAGE,
        recent_seconds=sessions.settings.recent_auth_seconds,
        lock=True,
    )
    target = await find_user_by_id(uow.session, target_id, lock=True)
    if target is None:
        raise UserNotFoundError()
    new_role = role.value if role is not None else target.role
    new_active = target.is_active if is_active is None else is_active
    if new_role == target.role and new_active == target.is_active:
        return None
    if (
        target.role == Role.ADMIN.value
        and target.is_active
        and target.email_verified_at is not None
        and (new_role != Role.ADMIN.value or not new_active)
    ):
        others = await uow.session.scalar(
            sa.select(sa.func.count())
            .select_from(User)
            .where(
                User.role == Role.ADMIN.value,
                User.is_active.is_(True),
                User.email_verified_at.is_not(None),
                User.id != target.id,
            )
        )
        if not others:
            raise LastActiveAdminError()
    if new_role == Role.ADMIN.value and target.email_verified_at is None:
        raise UnverifiedAdminError()
    old_role, old_active = target.role, target.is_active
    target.role, target.is_active = new_role, new_active
    await sessions.revoke(uow, user_id=target.id)
    record(
        uow,
        actor=AuditActor(ActorKind.ADMINISTRATOR, actor.user_id),
        action="identity.access_changed",
        target_type="user",
        target_id=target.id,
        outcome=AuditOutcome.SUCCEEDED,
        metadata={
            "old_role": old_role,
            "new_role": new_role,
            "old_active": old_active,
            "new_active": new_active,
        },
        allowed_metadata_keys=frozenset({"old_role", "new_role", "old_active", "new_active"}),
        correlation_id=correlation_id,
    )
