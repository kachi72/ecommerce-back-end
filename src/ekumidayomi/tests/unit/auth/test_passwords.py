"""Password operations preserve secrets and keep Argon2 work off the event loop."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from argon2 import PasswordHasher, extract_parameters
from argon2.low_level import Type

from ekumidayomi.auth import passwords
from ekumidayomi.auth.passwords import (
    hash_password,
    needs_rehash,
    validate_password,
    verify_password,
)
from ekumidayomi.users.errors import InvalidPasswordLengthError


async def test_argon2id_password_roundtrip() -> None:
    encoded = await hash_password("a long unicode Ẹkúmidáyọ̀mí passphrase")
    assert encoded.startswith("$argon2id$")
    assert await verify_password(encoded, "a long unicode Ẹkúmidáyọ̀mí passphrase")
    assert not await verify_password(encoded, "incorrect password")
    assert not await verify_password(None, "incorrect password")
    with pytest.raises(InvalidPasswordLengthError):
        await hash_password("short")


@pytest.mark.parametrize("length", [15, 128])
def test_length_boundaries_are_inclusive(length: int) -> None:
    value = "a" * length
    assert validate_password(value) == value


@pytest.mark.parametrize("length", [0, 1, 14, 129])
async def test_invalid_length_is_rejected_before_hashing(
    length: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    offload = AsyncMock()
    monkeypatch.setattr(asyncio, "to_thread", offload)
    with pytest.raises(InvalidPasswordLengthError):
        await hash_password("a" * length)
    offload.assert_not_called()


async def test_hashes_are_salted_and_use_current_argon2id_parameters() -> None:
    value = "quiet meadows beyond the river"
    first = await hash_password(value)
    second = await hash_password(value)
    assert first != second
    assert value not in first and value not in second
    parameters = extract_parameters(first)
    assert parameters.type is Type.ID
    assert parameters.time_cost == 3
    assert parameters.memory_cost == 65536
    assert parameters.parallelism == 4
    assert not needs_rehash(first)
    assert await verify_password(second, value)


async def test_old_argon2_parameters_require_rehash() -> None:
    old = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1, type=Type.ID)
    value = "quiet meadows beyond the river"
    encoded = await asyncio.to_thread(old.hash, value)
    assert needs_rehash(encoded)
    assert await verify_password(encoded, value)


async def test_hashing_preserves_spaces_case_and_unicode_normalization() -> None:
    value = "  Caf\u00e9 quiet meadows  "
    encoded = await hash_password(value)
    assert await verify_password(encoded, value)
    for changed in (value.strip(), value.casefold(), value.replace("\u00e9", "e\u0301")):
        assert not await verify_password(encoded, changed)


@pytest.mark.parametrize("encoded", ["not-an-argon2-hash", "$argon2id$broken", ""])
async def test_malformed_hash_fails_verification_without_escaping(encoded: str) -> None:
    assert not await verify_password(encoded, "quiet meadows beyond the river")


async def test_hash_and_verification_are_offloaded(monkeypatch: pytest.MonkeyPatch) -> None:
    offload = AsyncMock(wraps=asyncio.to_thread)
    monkeypatch.setattr(asyncio, "to_thread", offload)
    value = "quiet meadows beyond the river"
    encoded = await hash_password(value)
    offload.assert_awaited_once_with(passwords._HASHER.hash, value)
    offload.reset_mock()
    assert await verify_password(encoded, value)
    offload.assert_awaited_once_with(passwords._verify, encoded, value)


async def test_missing_credential_still_checks_dummy_hash_and_cannot_authenticate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    offload = AsyncMock(return_value=True)
    monkeypatch.setattr(asyncio, "to_thread", offload)
    value = "quiet meadows beyond the river"
    assert not await verify_password(None, value)
    offload.assert_awaited_once_with(passwords._verify, passwords._DUMMY_HASH, value)
