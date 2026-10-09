"""Run with uv run python -m ekumidayomi.auth.bootstrap --email ADDRESS --email-verified."""

import argparse
import asyncio
import getpass

import sqlalchemy as sa

from ekumidayomi.audit.model import ActorKind, AuditOutcome
from ekumidayomi.audit.service import AuditActor, record
from ekumidayomi.auth.challenge_model import PasswordCredential
from ekumidayomi.auth.password_policy import validate_new_password
from ekumidayomi.auth.passwords import hash_password
from ekumidayomi.core.settings import get_settings
from ekumidayomi.core.types import utc_now
from ekumidayomi.db.session import Database
from ekumidayomi.db.uow import SqlAlchemyUnitOfWork, UnitOfWork
from ekumidayomi.users.administration import lock_membership
from ekumidayomi.users.errors import BootstrapCompleteError, BootstrapConflictError
from ekumidayomi.users.model import Role, User
from ekumidayomi.users.repository import create_customer, find_user_by_email


async def bootstrap(uow: UnitOfWork, *, email: str, password: str) -> None:
    await lock_membership(uow)
    existing = await find_user_by_email(uow.session, email)
    if existing is not None:
        if (
            existing.role == Role.ADMIN.value
            and existing.is_active
            and existing.email_verified_at is not None
        ):
            return None
        raise BootstrapConflictError()
    count = await uow.session.scalar(
        sa.select(sa.func.count())
        .select_from(User)
        .where(
            User.role == Role.ADMIN.value,
            User.is_active.is_(True),
            User.email_verified_at.is_not(None),
        )
    )
    if count:
        raise BootstrapCompleteError()
    await validate_new_password(password)
    user = await create_customer(uow.session, email=email)
    user.role = Role.ADMIN.value
    user.email_verified_at = utc_now()
    uow.session.add(
        PasswordCredential(user_id=user.id, password_hash=await hash_password(password))
    )
    record(
        uow,
        actor=AuditActor(ActorKind.SYSTEM),
        action="identity.admin_bootstrapped",
        target_type="user",
        target_id=user.id,
        outcome=AuditOutcome.SUCCEEDED,
        metadata={},
        allowed_metadata_keys=frozenset(),
        correlation_id="admin-bootstrap",
    )


async def run(email: str, password: str) -> None:
    database = Database(get_settings())
    try:
        async with SqlAlchemyUnitOfWork(database.session_factory) as uow:
            await bootstrap(uow, email=email, password=password)
            await uow.commit()
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the first verified administrator.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--email-verified", action="store_true", required=True)
    args = parser.parse_args()
    password = getpass.getpass("Initial password: ")
    if password != getpass.getpass("Repeat password: "):
        parser.error("Passwords do not match.")
    asyncio.run(run(args.email, password))
    print("Administrator bootstrap complete.")


if __name__ == "__main__":
    main()
