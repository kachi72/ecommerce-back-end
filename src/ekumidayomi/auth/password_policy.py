"""New-password policy; hashing/verification remain separate from breach screening."""

import asyncio
import hashlib
import re
from abc import abstractmethod
from typing import Protocol

import httpx

from ekumidayomi.auth.passwords import validate_password
from ekumidayomi.users.errors import (
    BreachedPasswordError,
    CommonPasswordError,
    InvalidPasswordEncodingError,
    PasswordCheckUnavailableError,
)

_COMMON_PASSWORDS = frozenset(
    {"passwordpassword", "123456789012345", "12345678901234567890", "qwertyuiopasdfgh"}
)
_RANGE_ROW = re.compile(r"([0-9A-F]{35}):([0-9]{1,12})")
_MAX_RANGE_BYTES = 128 * 1024


class BreachChecker(Protocol):
    @abstractmethod
    async def is_breached(self, password: str) -> bool:
        """Check a complete password without transmitting it or its complete hash."""
        raise NotImplementedError


class HibpBreachChecker:
    """Use HIBP'S padded SHA-1 range lookup, not SHA-1 credential storage."""

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport

    async def is_breached(self, password: str) -> bool:
        digest = hashlib.sha1(password.encode("utf-8"), usedforsecurity=False).hexdigest().upper()
        try:
            async with asyncio.timeout(3):
                async with httpx.AsyncClient(
                    transport=self.transport,
                    timeout=2,
                    follow_redirects=False,
                    trust_env=False,
                    headers={
                        "Add-Padding": "true",
                        "Accept-Encoding": "identity",
                        "User-Agent": "Ekumidayomi-Password-Policy/1.0",
                    },
                ) as client:
                    async with client.stream(
                        "GET", f"https://api.pwnedpasswords.com/range/{digest[:5]}"
                    ) as response:
                        if response.status_code != 200:
                            raise ValueError("unexpected range status")
                        body = bytearray()
                        async for chunk in response.aiter_bytes(chunk_size=4096):
                            body.extend(chunk)
                            if len(body) > _MAX_RANGE_BYTES:
                                raise ValueError("range response exceeds limit")
            rows = body.decode("ascii").splitlines()
            if not rows:
                raise ValueError("empty range response")
            found = False
            seen: set[str] = set()
            for row in rows:
                match = _RANGE_ROW.fullmatch(row)
                if match is None:
                    raise ValueError("invalid range response")
                suffix, count = match.groups()
                if suffix in seen:
                    raise ValueError("duplicate range suffix")
                seen.add(suffix)
                if suffix == digest[5:] and int(count) > 0:
                    found = True
            return found
        except (httpx.HTTPError, TimeoutError, ValueError):
            raise PasswordCheckUnavailableError() from None


async def validate_new_password(value: str, *, checker: BreachChecker | None = None) -> str:
    """Allow any character mix, but reject common or breached whole passwords."""
    validate_password(value)
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise InvalidPasswordEncodingError() from None
    if len(set(value)) == 1 or value.casefold() in _COMMON_PASSWORDS:
        raise CommonPasswordError()
    resolved_checker = checker if checker is not None else HibpBreachChecker()
    if await resolved_checker.is_breached(value):
        raise BreachedPasswordError()
    return value
