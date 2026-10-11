"""All services for the user domain."""

from uuid import UUID

import sqlalchemy as sa

from ekumidayomi.auth.permissions import Permission, authorize
from ekumidayomi.auth.sessions import Actor
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users.address import Address
from ekumidayomi.users.errors import AddressLimitReachedError, AddressNotFoundError
from ekumidayomi.users.model import User
from ekumidayomi.users.schemas import AddressInput, ProfileInput


async def update_profile(uow: UnitOfWork, actor: Actor, data: ProfileInput) -> User:
    user = await authorize(uow, actor, Permission.PROFILE_WRITE, lock=True)
    user.display_name = data.display_name
    user.phone = data.phone
    await uow.commit()
    return user


async def list_addresses(uow: UnitOfWork, actor: Actor) -> list[Address]:
    await authorize(uow, actor, Permission.PROFILE_WRITE)
    return list(
        (
            await uow.session.scalars(
                sa.select(Address)
                .where(Address.user_id == actor.user_id)
                .order_by(Address.created_at, Address.id)
            )
        ).all()
    )


async def save_address(
    uow: UnitOfWork, actor: Actor, data: AddressInput, *, address_id: UUID | None = None
) -> Address:
    await authorize(uow, actor, Permission.PROFILE_WRITE, lock=True)
    row = None
    if address_id is not None:
        row = await uow.session.scalar(
            sa.select(Address).where(Address.id == address_id, Address.user_id == actor.user_id)
        )
        if row is None:
            raise AddressNotFoundError()
    else:
        count = await uow.session.scalar(
            sa.select(sa.func.count()).select_from(Address).where(Address.user_id == actor.user_id)
        )
        if count is not None and count >= 20:
            raise AddressLimitReachedError()
    if data.is_default:
        await uow.session.execute(
            sa.update(Address)
            .where(
                Address.user_id == actor.user_id,
                Address.kind == data.kind,
                Address.is_default.is_(True),
            )
            .values(is_default=False)
        )
        await uow.session.flush()
    if row is None:
        row = Address(user_id=actor.user_id)
        uow.session.add(row)
    for (
        name,
        value,
    ) in data.model_dump().items():
        setattr(row, name, value)
    await uow.session.flush()
    await uow.commit()
    return row


async def delete_address(uow: UnitOfWork, actor: Actor, address_id: UUID) -> None:
    await authorize(uow, actor, Permission.PROFILE_WRITE, lock=True)
    row = await uow.session.scalar(
        sa.select(Address).where(Address.id == address_id, Address.user_id == actor.user_id)
    )
    if row is None:
        raise AddressNotFoundError()
    await uow.session.delete(row)
    await uow.commit()
