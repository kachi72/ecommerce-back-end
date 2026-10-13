"""Private administrator queries with explicit durable permission checks."""

import sqlalchemy as sa

from ekumidayomi.auth.permissions import Permission, authorize
from ekumidayomi.auth.sessions import Actor
from ekumidayomi.core.types import Page, PageRequest
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users.model import Role, User
from ekumidayomi.users.repository import normalize_email


async def list_users(
    uow: UnitOfWork,
    actor: Actor,
    *,
    page: PageRequest,
    role: Role | None = None,
    is_active: bool | None = None,
    email: str | None = None,
) -> Page[User]:
    await authorize(uow, actor, Permission.USERS_READ)
    conditions = []
    if role is not None:
        conditions.append(User.role == role.value)
    if is_active is not None:
        conditions.append(User.is_active == is_active)
    if email is not None:
        conditions.append(User.email == normalize_email(email))
    total = int(
        await uow.session.scalar(sa.select(sa.func.count()).select_from(User).where(*conditions))
        or 0
    )
    rows = tuple(
        (
            await uow.session.scalars(
                sa.select(User)
                .where(*conditions)
                .order_by(User.created_at.desc(), User.id.desc())
                .limit(page.page_size)
                .offset(page.offset)
            )
        ).all()
    )
    return Page(items=rows, total_items=total, page=page.page, page_size=page.page_size)
