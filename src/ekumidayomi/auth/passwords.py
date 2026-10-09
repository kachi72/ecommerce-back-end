"""Argon2id password operations kept off the event loop."""

import asyncio
from typing import Final

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type

from ekumidayomi.users.errors import InvalidPasswordLengthError

_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, type=Type.ID)
_DUMMY_HASH = _HASHER.hash("timing-only-not-an-account-password")
MIN_PASSWORD_LEN: Final[int] = 15
MAX_PASSWORD_LEN: Final[int] = 128


def validate_password(value: str) -> str:
    if not MIN_PASSWORD_LEN <= len(value) <= MAX_PASSWORD_LEN:
        raise InvalidPasswordLengthError()
    return value


async def hash_password(value: str) -> str:
    """Hash or rehash locally; new credentials require validate_password first."""
    return await asyncio.to_thread(_HASHER.hash, validate_password(value))


def _verify(encoded: str, value: str) -> bool:
    try:
        return bool(_HASHER.verify(encoded, value))
    except (VerificationError, InvalidHashError):
        return False


async def verify_password(encoded: str | None, value: str) -> bool:
    valid = await asyncio.to_thread(_verify, encoded or _DUMMY_HASH, value)
    return encoded is not None and valid


def needs_rehash(encoded: str) -> bool:
    return _HASHER.check_needs_rehash(encoded)
