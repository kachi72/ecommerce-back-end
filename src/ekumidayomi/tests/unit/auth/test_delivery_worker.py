"""The worker entry point uses the central Resend group and always cleans up."""

import logging
import signal
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from ekumidayomi.auth import delivery_worker
from ekumidayomi.core.settings import Settings
from ekumidayomi.email.settings import ResendSettings
from ekumidayomi.outbox.operations import RecoveryReason


def configured_settings() -> tuple[Settings, ResendSettings]:
    resend = ResendSettings(
        api_key="test-provider-key",
        sender="notifications@example.com",
        fingerprint_key="k" * 32,
    )
    return Settings(_env_file=None, resend=resend), resend


def install_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Mock, Mock]:
    settings, _ = configured_settings()
    database = Mock(session_factory=Mock(), dispose=AsyncMock())
    uow = Mock(
        session=SimpleNamespace(execute=AsyncMock()),
        commit=AsyncMock(),
    )

    @asynccontextmanager
    async def context() -> AsyncIterator[Mock]:
        yield uow

    monkeypatch.setattr(delivery_worker, "get_settings", lambda: settings)
    monkeypatch.setattr(delivery_worker, "Database", Mock(return_value=database))
    monkeypatch.setattr(delivery_worker, "ResendEmailSender", Mock())
    monkeypatch.setattr(
        delivery_worker,
        "SqlAlchemyUnitOfWork",
        lambda factory: context(),
    )
    monkeypatch.setattr(signal, "getsignal", Mock(return_value=None))
    monkeypatch.setattr(signal, "signal", Mock())
    return database, uow


async def test_run_once_uses_resend_without_requiring_a_message_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, resend = configured_settings()
    database = Mock(dispose=AsyncMock())
    sender_factory = Mock()
    worker = Mock(run=AsyncMock())
    monkeypatch.setattr(delivery_worker, "get_settings", lambda: settings)
    monkeypatch.setattr(delivery_worker, "Database", Mock(return_value=database))
    monkeypatch.setattr(delivery_worker, "ResendEmailSender", sender_factory)
    monkeypatch.setattr(delivery_worker, "LeasedOutboxWorker", Mock(return_value=worker))
    monkeypatch.setattr(signal, "getsignal", Mock(return_value=None))
    monkeypatch.setattr(signal, "signal", Mock())

    assert await delivery_worker.run(command="run", once=True) == 0

    assert sender_factory.call_args.args[0] is resend
    worker.run.assert_awaited_once()
    assert worker.run.await_args is not None
    assert worker.run.await_args.kwargs["once"] is True
    database.dispose.assert_awaited_once()


async def test_missing_provider_config_fails_before_opening_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(_env_file=None, resend=None)
    database_factory = Mock()
    monkeypatch.setattr(delivery_worker, "get_settings", lambda: settings)
    monkeypatch.setattr(delivery_worker, "Database", database_factory)

    with pytest.raises(RuntimeError, match="Resend settings are required"):
        await delivery_worker.run(command="run", once=True)

    database_factory.assert_not_called()


def test_replay_cli_accepts_configuration_fixed(monkeypatch: pytest.MonkeyPatch) -> None:
    message_id = uuid4()
    runner = AsyncMock(return_value=0)
    monkeypatch.setattr(delivery_worker, "run", runner)
    monkeypatch.setattr(
        sys,
        "argv",
        ["worker", "replay", "--message-id", str(message_id), "--reason", "configuration_fixed"],
    )

    with pytest.raises(SystemExit) as caught:
        delivery_worker.main()

    assert caught.value.code == 0
    runner.assert_awaited_once_with(
        command="replay",
        once=False,
        message_id=message_id,
        reason=RecoveryReason.CONFIGURATION_FIXED,
    )


@pytest.mark.parametrize(("healthy", "expected"), [(True, 0), (False, 1)])
async def test_status_returns_health_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    healthy: bool,
    expected: int,
) -> None:
    database, uow = install_runtime(monkeypatch)
    health = AsyncMock(return_value={"healthy": healthy})
    monkeypatch.setattr(delivery_worker, "health", health)

    assert await delivery_worker.run(command="status") == expected

    health.assert_awaited_once()
    health_call = health.await_args
    assert health_call is not None
    assert health_call.args[0] is uow
    assert health_call.args[1:] == (
        "auth_email",
        ("email_challenge_requested",),
    )
    uow.commit.assert_not_awaited()
    database.dispose.assert_awaited_once()


async def test_replay_and_resume_commit_recovery_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, uow = install_runtime(monkeypatch)
    replay = AsyncMock()
    resume = AsyncMock()
    monkeypatch.setattr(delivery_worker, "replay", replay)
    monkeypatch.setattr(delivery_worker, "resume", resume)
    message_id = uuid4()

    assert (
        await delivery_worker.run(
            command="replay",
            message_id=message_id,
            reason=RecoveryReason.TRANSIENT_RESOLVED,
        )
        == 0
    )
    replay.assert_awaited_once()
    replay_call = replay.await_args
    assert replay_call is not None
    assert replay_call.args[:3] == (
        uow,
        message_id,
        RecoveryReason.TRANSIENT_RESOLVED,
    )
    uow.commit.assert_awaited_once()

    uow.commit.reset_mock()
    assert await delivery_worker.run(command="resume") == 0
    resume.assert_awaited_once_with(uow, "auth_email")
    uow.commit.assert_awaited_once()
    assert database.dispose.await_count == 2


@pytest.mark.parametrize(
    ("command", "message_id", "reason", "message"),
    [
        ("replay", None, None, "replay requires"),
        ("unsupported", None, None, "unsupported command"),
    ],
)
async def test_invalid_worker_commands_still_dispose_resources(
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    message_id: Any,
    reason: Any,
    message: str,
) -> None:
    database, _ = install_runtime(monkeypatch)

    with pytest.raises(ValueError, match=message):
        await delivery_worker.run(
            command=command,
            message_id=message_id,
            reason=reason,
        )

    database.dispose.assert_awaited_once()


def test_cli_converts_worker_failure_to_exit_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = AsyncMock(side_effect=RuntimeError("private failure"))
    error = Mock()
    monkeypatch.setattr(delivery_worker, "run", runner)
    monkeypatch.setattr(logging.getLogger(delivery_worker.__name__), "error", error)
    monkeypatch.setattr(sys, "argv", ["worker", "status"])

    with pytest.raises(SystemExit) as caught:
        delivery_worker.main()

    assert caught.value.code == 1
    error.assert_called_once_with("worker_stopped")
