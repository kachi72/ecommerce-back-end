"""Session lifecycle with durable authorization and cache-only lookup hints."""

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

import sqlalchemy as sa
from redis.asyncio import Redis
from redis.exceptions import RedisError

from ekumidayomi.auth.model import AuthSession
from ekumidayomi.auth.settings import AuthSettings
from ekumidayomi.core.types import utc_now
from ekumidayomi.db.uow import UnitOfWork
from ekumidayomi.users.errors import AuthenticationRequiredError
from ekumidayomi.users.model import Role, User


@dataclass(frozen=True, slots=True)
class Actor:
    user_id: UUID
    session_id: UUID
    role: Role
    authenticated_at: datetime


def digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("ascii")).hexdigest()


class SessionService:
    def __init__(self, redis: Redis, *, namespace: str, settings: AuthSettings) -> None:
        self.redis = redis
        self.namespace = namespace
        self.settings = settings

    def key(self, secret_hash: str) -> str:
        return f"ekumidayomi:{self.namespace}:auth:v1:session:{secret_hash}"

    async def issue(self, uow: UnitOfWork, user: User) -> str:
        if not user.is_active or user.email_verified_at is None:
            raise AuthenticationRequiredError()
        secret = secrets.token_urlsafe(32)
        now = utc_now()
        row = AuthSession(
            user_id=user.id,
            secret_hash=digest(secret),
            created_at=now,
            authenticated_at=now,
            expires_at=now + timedelta(seconds=self.settings.session_seconds),
        )
        uow.session.add(row)
        await uow.session.flush()
        return secret

    async def resolve(self, uow: UnitOfWork, secret: str | None) -> Actor:
        if secret is None or re.fullmatch(r"[A-Za-z0-9_-]{43}", secret) is None:
            raise AuthenticationRequiredError()
        secret_hash = digest(secret)
        hint: UUID | None = None
        try:
            cached = await self.redis.get(self.key(secret_hash))
            if cached:
                hint = UUID(cached.decode() if isinstance(cached, bytes) else str(cached))
        except (RedisError, ValueError, TypeError):
            hint = None
        statement = sa.select(AuthSession, User).join(User, User.id == AuthSession.user_id)

        conditions = [
            AuthSession.secret_hash == secret_hash,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > utc_now(),
            User.is_active.is_(True),
            User.email_verified_at.is_not(None),
        ]
        result = None
        if hint is not None:
            result = (
                await uow.session.execute(statement.where(*conditions, AuthSession.id == hint))
            ).first()
        if result is None:
            result = (await uow.session.execute(statement.where(*conditions))).first()
        if result is None:
            raise AuthenticationRequiredError()
        row, user = result
        try:
            role = Role(user.role)
        except ValueError:
            raise AuthenticationRequiredError from None
        try:
            await self.redis.set(self.key(secret_hash), str(row.id), ex=self.settings.cache_seconds)
        except RedisError:
            pass
        return Actor(user.id, row.id, role, row.authenticated_at)

    async def revoke(
        self, uow: UnitOfWork, *, user_id: UUID, session_id: UUID | None = None
    ) -> None:
        condition = [AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)]
        if session_id is not None:
            condition.append(AuthSession.id == session_id)
        hashes = tuple(
            (
                await uow.session.scalars(
                    sa.update(AuthSession)
                    .where(*condition)
                    .values(revoked_at=utc_now())
                    .returning(AuthSession.secret_hash)
                )
            ).all()
        )

        async def invalidate() -> None:
            if hashes:
                try:
                    await self.redis.delete(*(self.key(value) for value in hashes))
                except RedisError:
                    return None

        uow.after_commit(invalidate)
