"""Regression coverage for the centrally loaded Resend configuration."""

import pytest

from ekumidayomi.core.settings import Settings


def test_root_loads_resend_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EKUMIDAYOMI_RESEND__API_KEY", "test-provider-key")
    monkeypatch.setenv("EKUMIDAYOMI_RESEND__SENDER", "notifications@example.com")
    monkeypatch.setenv("EKUMIDAYOMI_RESEND__FINGERPRINT_KEY", "k" * 32)
    monkeypatch.setenv("EKUMIDAYOMI_RESEND__TIMEOUT_SECONDS", "8")

    settings = Settings(_env_file=None)

    assert settings.resend is not None
    assert settings.resend.api_key.get_secret_value() == "test-provider-key"
    assert settings.resend.sender == "notifications@example.com"
    assert settings.resend.fingerprint_key.get_secret_value() == "k" * 32
    assert settings.resend.timeout_seconds == 8
    assert "test-provider-key" not in repr(settings)
