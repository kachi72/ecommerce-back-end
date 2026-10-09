"""Policy and range-adapter tests never call the live breach service."""

import asyncio
import hashlib
from collections.abc import AsyncIterator

import httpx
import pytest

from ekumidayomi.auth import password_policy
from ekumidayomi.auth.password_policy import HibpBreachChecker, validate_new_password
from ekumidayomi.users.errors import (
    BreachedPasswordError,
    CommonPasswordError,
    InvalidPasswordEncodingError,
    InvalidPasswordLengthError,
    PasswordCheckUnavailableError,
)


class StubChecker:
    def __init__(self, *, breached: bool = False) -> None:
        self.breached = breached
        self.checked: list[str] = []

    async def is_breached(self, password: str) -> bool:
        self.checked.append(password)
        return self.breached


@pytest.mark.parametrize(
    "value",
    [
        "quietmeadowsbeyondtheriver",
        "QUIETMEADOWSBEYONDTHERIVER",
        "731946208573194620857319",
        "!@#$%^&*()_+-=[]{}",
        "  quiet meadows beyond the river  ",
        "Ẹkúmidáyọ̀mí quiet meadows",
        "quietmeadowwalk",
        "quietmeadows" * 10 + "pathways",
    ],
)
async def test_no_required_character_mix_and_no_password_mutation(value: str) -> None:
    checker = StubChecker()
    assert await validate_new_password(value, checker=checker) == value
    assert checker.checked == [value]


@pytest.mark.parametrize(
    "value, error_type",
    [
        ("a" * 15, CommonPasswordError),
        ("a" * 128, CommonPasswordError),
        (" " * 15, CommonPasswordError),
        ("passwordpassword", CommonPasswordError),
        ("PASSWORDPASSWORD", CommonPasswordError),
        ("123456789012345", CommonPasswordError),
        ("12345678901234567890", CommonPasswordError),
        ("qwertyuiopasdfgh", CommonPasswordError),
        ("short", InvalidPasswordLengthError),
        ("a" * 14, InvalidPasswordLengthError),
        ("a" * 129, InvalidPasswordLengthError),
        ("\ud800" * 15, InvalidPasswordEncodingError),
    ],
)
async def test_local_denial_happens_before_network(value: str, error_type: type[Exception]) -> None:
    checker = StubChecker()
    with pytest.raises(error_type):
        await validate_new_password(value, checker=checker)
    assert checker.checked == []


async def test_breached_password_is_rejected_despite_adequate_length() -> None:
    checker = StubChecker(breached=True)
    with pytest.raises(BreachedPasswordError) as caught:
        await validate_new_password("quietmeadowsbeyondtheriver", checker=checker)
    assert caught.value.code == "unsafe_password"


@pytest.mark.parametrize("count, expected", [(1, True), (0, False)])
async def test_range_request_discloses_only_prefix_and_ignores_padding(
    count: int, expected: bool
) -> None:
    password = "quietmeadowsbeyondtheriver"
    digest = hashlib.sha1(password.encode(), usedforsecurity=False).hexdigest().upper()
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert str(request.url) == f"https://api.pwnedpasswords.com/range/{digest[:5]}"
        assert request.headers["Add-Padding"] == "true"
        assert request.headers["Accept-Encoding"] == "identity"
        assert request.extensions["timeout"] == dict.fromkeys(
            ("connect", "read", "write", "pool"), 2
        )
        assert request.method == "GET" and request.content == b""
        assert "authorization" not in request.headers and "cookie" not in request.headers
        return httpx.Response(200, text=f"{digest[5:]}:{count}\r\n")

    checker = HibpBreachChecker(transport=httpx.MockTransport(respond))
    assert await checker.is_breached(password) is expected
    assert len(requests) == 1


async def test_absent_suffix_is_not_a_match() -> None:
    checker = HibpBreachChecker(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=f"{'0' * 35}:7\r\n"))
    )
    assert not await checker.is_breached("quietmeadowsbeyondtheriver")


@pytest.mark.parametrize(
    "status, body",
    [
        (503, b"unavailable"),
        (404, b"not found"),
        (429, b"rate limited"),
        (302, b"redirect"),
        (200, b""),
        (200, b"invalid row"),
        (200, b"A" * 35 + b":-1"),
        (200, b"A" * 35 + b":1\n" + b"A" * 35 + b":2"),
        (200, b"\xff"),
        (200, b"x" * (128 * 1024 + 1)),
    ],
    ids=[
        "unavailable",
        "not-found",
        "limited",
        "redirect",
        "empty",
        "bad-row",
        "negative-count",
        "duplicate",
        "encoding",
        "oversized",
    ],
)
async def test_service_failures_do_not_mark_a_password_safe(status: int, body: bytes) -> None:
    checker = HibpBreachChecker(
        transport=httpx.MockTransport(lambda request: httpx.Response(status, content=body))
    )
    with pytest.raises(PasswordCheckUnavailableError) as caught:
        await validate_new_password("quietmeadowsbeyondtheriver", checker=checker)
    assert caught.value.code == "password_check_unavailable"
    assert "quietmeadows" not in str(caught.value)
    assert caught.value.details == {}


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ReadTimeout, TimeoutError])
async def test_transport_failure_is_fail_closed(failure: type[Exception]) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        raise failure("test-only failure")

    checker = HibpBreachChecker(transport=httpx.MockTransport(respond))
    with pytest.raises(PasswordCheckUnavailableError):
        await validate_new_password("quietmeadowsbeyondtheriver", checker=checker)


async def test_default_checker_is_mandatory(monkeypatch: pytest.MonkeyPatch) -> None:
    checker = StubChecker(breached=True)
    monkeypatch.setattr(password_policy, "HibpBreachChecker", lambda: checker)
    value = "quietmeadowsbeyondtheriver"
    with pytest.raises(BreachedPasswordError):
        await validate_new_password(value)
    assert checker.checked == [value]


@pytest.mark.parametrize("value", ["ab" * 7 + "c", "ab" * 64, "\u00e9" * 14 + "x"])
async def test_policy_uses_character_count_not_utf8_byte_count(value: str) -> None:
    checker = StubChecker()
    assert await validate_new_password(value, checker=checker) == value
    assert checker.checked == [value]


async def test_range_scans_all_rows_not_just_first_match() -> None:
    value = "quietmeadowsbeyondtheriver"
    digest = hashlib.sha1(value.encode(), usedforsecurity=False).hexdigest().upper()
    body = f"{'0' * 35}:0\r\n{digest[5:]}:12\r\n{'F' * 35}:8\r\n"
    checker = HibpBreachChecker(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=body))
    )
    assert await checker.is_breached(value)


async def test_match_does_not_hide_malformed_trailing_rows() -> None:
    value = "quietmeadowsbeyondtheriver"
    digest = hashlib.sha1(value.encode(), usedforsecurity=False).hexdigest().upper()
    checker = HibpBreachChecker(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=f"{digest[5:]}:12\ninvalid")
        )
    )
    with pytest.raises(PasswordCheckUnavailableError):
        await checker.is_breached(value)


async def test_redirect_is_not_followed() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://untrusted.example/range"})

    checker = HibpBreachChecker(transport=httpx.MockTransport(respond))
    with pytest.raises(PasswordCheckUnavailableError):
        await checker.is_breached("quietmeadowsbeyondtheriver")
    assert len(requests) == 1
    assert requests[0].url.host == "api.pwnedpasswords.com"


async def test_failure_does_not_expose_password_hash_prefix_or_transport_error() -> None:
    value = "quietmeadowsbeyondtheriver"
    digest = hashlib.sha1(value.encode(), usedforsecurity=False).hexdigest().upper()

    def respond(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"secret {value} {digest} {request.url}", request=request)

    checker = HibpBreachChecker(transport=httpx.MockTransport(respond))
    with pytest.raises(PasswordCheckUnavailableError) as caught:
        await validate_new_password(value, checker=checker)
    error = caught.value
    public = f"{error!s} {error!r} {error.message} {error.details}"
    for secret in (value, digest, digest[:5], "pwnedpasswords.com"):
        assert secret not in public
    assert error.details == {}
    assert error.__cause__ is None and error.__suppress_context__


class WaitingStream(httpx.AsyncByteStream):
    """Yield control without producing data; timeout/cancellation must close it."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.started.set()
        await asyncio.Event().wait()
        yield b"unreachable"

    async def aclose(self) -> None:
        self.closed = True


async def test_total_deadline_closes_slow_stream_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_timeout = asyncio.timeout

    def immediate_timeout(delay: float) -> asyncio.Timeout:
        assert delay == 3
        return real_timeout(0)

    monkeypatch.setattr(asyncio, "timeout", immediate_timeout)
    stream = WaitingStream()
    checker = HibpBreachChecker(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
    )
    with pytest.raises(PasswordCheckUnavailableError):
        await checker.is_breached("quietmeadowsbeyondtheriver")
    assert stream.started.is_set()
    assert stream.closed


async def test_caller_cancellation_is_not_converted_into_policy_failure() -> None:
    stream = WaitingStream()
    checker = HibpBreachChecker(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
    )
    async with asyncio.timeout(1):
        task = asyncio.create_task(checker.is_breached("quietmeadowsbeyondtheriver"))
        try:
            await stream.started.wait()
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    assert stream.closed
