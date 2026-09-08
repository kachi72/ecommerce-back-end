"""User persistence without transaction ownership."""

from uuid import UUID

import sqlalchemy as sa
from email_validator import EmailNotValidError, validate_email
from sqlalchemy.ext.asyncio import AsyncSession

from ekumidayomi.users.errors import InvalidEmailError
from ekumidayomi.users.model import Role, User


def normalize_email(value: str) -> str:
    try:
        return str(validate_email(value.strip(), check_deliverability=False).normalized).casefold()
    except EmailNotValidError:
        raise InvalidEmailError() from None


async def by_email(session: AsyncSession, email: str) -> User | None:
    user = await session.scalar(sa.select(User).where(User.email == normalize_email(email)))
    return user


async def by_id(session: AsyncSession, user_id: UUID, *, lock: bool = False) -> User | None:
    statement = sa.select(User).where(User.id == user_id)
    if lock:
        statement = statement.with_for_update()
    user = await session.scalar(statement.execution_options(populate_existing=True))
    return user


async def create_customer(session: AsyncSession, *, email: str) -> User:
    user = User(email=normalize_email(email), role=Role.CUSTOMER.value, is_active=True)
    session.add(user)
    await session.flush()
    return user
