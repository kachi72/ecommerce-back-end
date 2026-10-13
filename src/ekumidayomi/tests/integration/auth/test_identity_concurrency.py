"""Identity race tests use distinct PostgreSQL connections and transactions."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import fakeredis.aioredis
import sqlalchemy as sa
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from ekumidayomi.auth.bootstrap import bootstrap
from ekumidayomi.auth.challenge_model import EmailChallenge
from ekumidayomi.auth.challenges import derive_code
from ekumidayomi.auth.registration import begin_registration, complete_registration
from ekumidayomi.auth.sessions import Actor, SessionService
from ekumidayomi.auth.settings import AuthSettings
from ekumidayomi.core.types import utc_now
from ekumidayomi.db.uow import SqlAlchemyUnitOfWork, UnitOfWork
from ekumidayomi.tests.integration.conftest import set_search_path
from ekumidayomi.users.administration import change_access
from ekumidayomi.users.errors import InvalidChallengeError, LastActiveAdminError
from ekumidayomi.users.model import Role, User
from ekumidayomi.users.repository import create_customer, find_user_by_email


@asynccontextmanager
async def independent_uow(
    seed: AsyncConnection,
    schema: str,
) -> AsyncIterator[UnitOfWork]:
    async with seed.engine.connect() as connection:
        await set_search_path(connection, f'"{schema}", public')
        await connection.commit()
        factory = async_sessionmaker(bind=connection, expire_on_commit=False, autoflush=False)
        async with SqlAlchemyUnitOfWork(factory) as uow:
            yield uow


async def test_two_admin_self_demotions_preserve_one_active_admin(
    identity_uow: UnitOfWork,
    database_connection: AsyncConnection,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await bootstrap(
        identity_uow,
        email="first@example.com",
        password="quiet meadows beyond the river",
    )
    first = await find_user_by_email(identity_uow.session, "first@example.com")
    assert first is not None
    second = await create_customer(identity_uow.session, email="second@example.com")
    second.role = Role.ADMIN.value
    second.email_verified_at = utc_now()
    sessions = SessionService(fake_redis, namespace="test", settings=AuthSettings())
    secrets = [await sessions.issue(identity_uow, user) for user in (first, second)]
    await identity_uow.commit()
    actors = [await sessions.resolve(identity_uow, secret) for secret in secrets]
    schema = await identity_uow.session.scalar(sa.text("SELECT current_schema()"))
    assert isinstance(schema, str)
    await identity_uow.commit()

    async def demote(actor: Actor) -> bool:
        async with independent_uow(database_connection, schema) as uow:
            try:
                await change_access(
                    uow,
                    sessions,
                    actor=actor,
                    target_id=actor.user_id,
                    role=Role.CUSTOMER,
                    is_active=None,
                    correlation_id="race-demotion",
                )
            except LastActiveAdminError:
                return False
            return True

    outcomes = await asyncio.wait_for(
        asyncio.gather(*(demote(actor) for actor in actors)),
        timeout=10,
    )
    assert sum(outcomes) == 1
    remaining = await identity_uow.session.scalar(
        sa.select(sa.func.count())
        .select_from(User)
        .where(
            User.role == Role.ADMIN.value,
            User.is_active.is_(True),
            User.email_verified_at.is_not(None),
        )
    )
    assert remaining == 1


async def test_two_verifications_create_one_account(
    identity_uow: UnitOfWork,
    database_connection: AsyncConnection,
) -> None:
    settings = AuthSettings(challenge_keys={"v1": SecretStr("k" * 32)})
    identifier = await begin_registration(identity_uow, "race@example.com", settings)
    challenge = await identity_uow.session.get(EmailChallenge, identifier)
    assert challenge is not None
    code = derive_code(challenge, settings)
    schema = await identity_uow.session.scalar(sa.text("SELECT current_schema()"))
    assert isinstance(schema, str)
    await identity_uow.commit()

    async def verify() -> bool:
        async with independent_uow(database_connection, schema) as uow:
            try:
                await complete_registration(
                    uow,
                    challenge_id=identifier,
                    code=code,
                    password="quiet meadows beyond the river",
                    settings=settings,
                )
            except InvalidChallengeError:
                return False
            return True

    outcomes = await asyncio.wait_for(
        asyncio.gather(verify(), verify()),
        timeout=10,
    )
    assert sum(outcomes) == 1
    count = await identity_uow.session.scalar(
        sa.select(sa.func.count()).select_from(User).where(User.email == "race@example.com")
    )
    assert count == 1
