import hashlib
import hmac
import secrets

from pydantic import ValidationError as PydanticValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError

from ekumidayomi.auth.oidc.contracts import Attempt
from ekumidayomi.auth.oidc.settings import ProviderName
from ekumidayomi.users.errors import (
    ExternalLoginFailedError,
    IdentityUnavailableError,
)


def state_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class AttemptStore:
    def __init__(self, redis: Redis, *, namespace: str, ttl: int) -> None:
        self.redis, self.namespace, self.ttl = redis, namespace, ttl

    def key(self, state: str) -> str:
        return f"ekumidayomi:{self.namespace}:auth:v1:oidc:{state_hash(state)}"

    async def create(self, attempt: Attempt) -> str:
        state = secrets.token_urlsafe(32)
        try:
            stored = await self.redis.set(
                self.key(state), attempt.model_dump_json(), ex=self.ttl, nx=True
            )
        except RedisError:
            raise IdentityUnavailableError() from None
        if not stored:
            raise IdentityUnavailableError()
        return state

    async def consume(self, state: str, browser: str, provider: ProviderName) -> Attempt:
        if not 20 <= len(state) <= 128 or not 20 <= len(browser) <= 128:
            raise ExternalLoginFailedError()
        try:
            raw = await self.redis.getdel(self.key(state))
        except RedisError:
            raise IdentityUnavailableError() from None
        if raw is None:
            raise ExternalLoginFailedError()
        try:
            attempt = Attempt.model_validate_json(raw)
        except (PydanticValidationError, TypeError):
            raise ExternalLoginFailedError() from None
        if attempt.provider != provider or not hmac.compare_digest(
            attempt.browser_hash, state_hash(browser)
        ):
            raise ExternalLoginFailedError()
        return attempt
