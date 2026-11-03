"""OIDC configuration fails closed before application startup."""

import pytest
from pydantic import ValidationError

from ekumidayomi.auth.oidc.settings import OidcSettings, ProviderConfig
from ekumidayomi.auth.settings import AuthSettings


def enabled_provider(**changes: object) -> ProviderConfig:
    values: dict[str, object] = {
        "enabled": True,
        "client_id": "client-id",
        "client_secret": "client-secret",
        "redirect_uri": "https://api.example.com/api/v1/auth/oidc/google/callback",
    }
    values.update(changes)
    return ProviderConfig.model_validate(values)


def test_google_can_be_enabled_with_exact_https_callback() -> None:
    settings = AuthSettings(oidc=OidcSettings(google=enabled_provider()))

    assert settings.oidc.google.enabled is True


@pytest.mark.parametrize(
    "changes",
    [
        {"client_id": ""},
        {"client_secret": ""},
        {"redirect_uri": "http://api.example.com/callback"},
        {"redirect_uri": "https://user@api.example.com/callback"},
        {"redirect_uri": "https://api.example.com/callback?next=/profile"},
        {"redirect_uri": "https://api.example.com/callback#fragment"},
    ],
)
def test_enabled_provider_rejects_incomplete_or_inexact_configuration(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        enabled_provider(**changes)


def test_yahoo_remains_disabled_until_pkce_is_verified() -> None:
    with pytest.raises(ValidationError, match="Yahoo S256"):
        OidcSettings(yahoo=enabled_provider())

    settings = OidcSettings(yahoo=enabled_provider(pkce_verified=True))
    assert settings.yahoo.enabled is True
