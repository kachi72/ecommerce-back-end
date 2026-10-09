import fakeredis.aioredis
import pytest

from ekumidayomi.auth.bootstrap import bootstrap
from ekumidayomi.auth.sessions import SessionService
from ekumidayomi.auth.settings import AuthSettings
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users.administration import change_access
from ekumidayomi.users.errors import LastActiveAdminError
from ekumidayomi.users.model import Role
from ekumidayomi.users.repository import find_user_by_email


async def test_last_admin_cannot_demote_self(
    identity_uow: UnitOfWork, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    await bootstrap(identity_uow, email="admin@example.com", password="long bootstrap password")
    await identity_uow.commit()
    user = await find_user_by_email(identity_uow.session, "admin@example.com")
    assert user is not None
    sessions = SessionService(fake_redis, namespace="test", settings=AuthSettings())
    secret = await sessions.issue(identity_uow, user)
    await identity_uow.commit()
    actor = await sessions.resolve(identity_uow, secret)
    with pytest.raises(LastActiveAdminError, match="final active"):
        await change_access(
            identity_uow,
            sessions,
            actor=actor,
            target_id=user.id,
            role=Role.CUSTOMER,
            is_active=None,
            correlation_id="test-demotion",
        )
