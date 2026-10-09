"""Named audit evidence participates in the caller's real PostgreSQL transaction."""

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from ekumidayomi.audit.model import ActorKind, AuditRecord
from ekumidayomi.audit.service import AuditActor, record_event
from ekumidayomi.auth.events import RegistrationCompletedEvent
from ekumidayomi.db.uow import SqlAlchemyUnitOfWork
from ekumidayomi.users.model import User


@pytest.mark.parametrize("finish", ["commit", "rollback", "uncommitted-exit"])
async def test_business_change_and_audit_share_transaction(
    database_connection: AsyncConnection, finish: str
) -> None:
    factory = async_sessionmaker(bind=database_connection, expire_on_commit=False)
    async with SqlAlchemyUnitOfWork(factory) as uow:
        user = User(email="audit-customer@example.com")
        uow.session.add(user)
        await uow.session.flush()
        user_id = user.id
        audit = record_event(
            uow,
            RegistrationCompletedEvent(
                actor=AuditActor(ActorKind.CUSTOMER, actor_id=user_id),
                target_id=user_id,
                correlation_id="registration-transaction",
            ),
        )
        assert audit in uow.session.new
        await uow.session.flush()
        audit_id = audit.id
        if finish == "commit":
            await uow.commit()
        elif finish == "rollback":
            await uow.rollback()

    async with AsyncSession(database_connection) as session:
        restored_user = await session.get(User, user_id)
        restored_audit = await session.get(AuditRecord, audit_id)
        if finish == "commit":
            assert restored_user is not None and restored_audit is not None
            assert restored_audit.action == "auth.registration_completed"
            assert restored_audit.target_type == "user"
            assert restored_audit.target_id == user_id
            assert restored_audit.actor_kind == "customer"
            assert restored_audit.actor_id == user_id
            assert restored_audit.outcome == "succeeded"
            assert restored_audit.correlation_id == "registration-transaction"
            assert restored_audit.occurred_at.utcoffset() is not None
            assert restored_audit.metadata_ == {}
        else:
            assert restored_user is None and restored_audit is None


async def test_exception_rolls_back_business_change_and_audit(
    database_connection: AsyncConnection,
) -> None:
    factory = async_sessionmaker(bind=database_connection, expire_on_commit=False)
    with pytest.raises(RuntimeError, match="abort registration"):
        async with SqlAlchemyUnitOfWork(factory) as uow:
            user = User(email="audit-rollback@example.com")
            uow.session.add(user)
            await uow.session.flush()
            record_event(
                uow,
                RegistrationCompletedEvent(
                    actor=AuditActor(ActorKind.SYSTEM),
                    target_id=user.id,
                    correlation_id="registration-abort",
                ),
            )
            await uow.session.flush()
            raise RuntimeError("abort registration")
    async with AsyncSession(database_connection) as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(User)) == 0
        assert await session.scalar(sa.select(sa.func.count()).select_from(AuditRecord)) == 0
