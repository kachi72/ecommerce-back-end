"""Customer address operations remain owner-scoped."""

import fakeredis.aioredis
import pytest

from ekumidayomi.auth.sessions import SessionService
from ekumidayomi.auth.settings import AuthSettings
from ekumidayomi.core.types import utc_now
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users import service as users_service
from ekumidayomi.users.errors import AddressNotFoundError
from ekumidayomi.users.repository import create_customer
from ekumidayomi.users.schemas import AddressInput


async def test_saved_addresses_are_owner_scoped(
    identity_uow: UnitOfWork,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    first = await create_customer(identity_uow.session, email="owner@example.com")
    second = await create_customer(identity_uow.session, email="other@example.com")
    first.email_verified_at = second.email_verified_at = utc_now()
    sessions = SessionService(fake_redis, namespace="test", settings=AuthSettings())
    owner_secret = await sessions.issue(identity_uow, first)
    other_secret = await sessions.issue(identity_uow, second)
    await identity_uow.commit()
    owner = await sessions.resolve(identity_uow, owner_secret)
    other = await sessions.resolve(identity_uow, other_secret)
    address_input = AddressInput(
        kind="shipping",
        recipient="Owner",
        line1="1 Main Street",
        city="Lagos",
        region="Lagos",
        country_code="NG",
        is_default=True,
    )

    address = await users_service.save_address(identity_uow, owner, address_input)
    assert await users_service.list_addresses(identity_uow, other) == []
    with pytest.raises(AddressNotFoundError):
        await users_service.delete_address(identity_uow, other, address.id)

    replacement = await users_service.save_address(identity_uow, owner, address_input)
    rows = await users_service.list_addresses(identity_uow, owner)
    assert sum(row.is_default for row in rows) == 1
    assert next(row.id for row in rows if row.is_default) == replacement.id
