"""The worker entry point uses the central Resend group and always cleans up."""

import signal
import sys
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from ekumidayomi.auth import delivery_worker
from ekumidayomi.core.settings import Settings
from ekumidayomi.email.settings import ResendSettings
from ekumidayomi.outbox.operations import RecoveryReason


async def test_run_once_uses_resend_without_requiring_a_message_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resend = ResendSettings(
        api_key="test-provider-key",
        sender="notifications@example.com",
        fingerprint_key="k" * 32,
    )
    settings = Settings(_env_file=None, resend=resend)
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
