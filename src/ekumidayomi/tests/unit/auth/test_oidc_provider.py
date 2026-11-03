"""OIDC adapters validate pinned endpoints, PKCE, signatures, and claims."""

import time
from collections.abc import Mapping
from typing import Any
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from joserfc import jwt
from joserfc.jwk import generate_key

from ekumidayomi.auth.oidc.contracts import Attempt, Identity
from ekumidayomi.auth.oidc.providers import OidcProvider
from ekumidayomi.auth.oidc.settings import ISSUERS, ProviderConfig, ProviderName
from ekumidayomi.users.errors import ExternalLoginFailedError


def provider() -> OidcProvider:
    return OidcProvider(
        ProviderName.GOOGLE,
        ProviderConfig(
            client_id="client-id",
            client_secret="client-secret",
            redirect_uri="https://api.example.com/callback",
        ),
        5.0,
    )


def attempt(*, intent: str = "login") -> Attempt:
    actor_id = uuid4() if intent != "login" else None
    session_id = uuid4() if intent != "login" else None
    return Attempt.model_validate(
        {
            "provider": "google",
            "intent": intent,
            "browser_hash": "hash",
            "nonce": "nonce-value",
            "verifier": "v" * 64,
            "redirect_uri": "https://api.example.com/callback",
            "actor_id": actor_id,
            "session_id": session_id,
            "started_at": int(time.time()),
        }
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://accounts.google.com/token",
        "https://evil.example/token",
        "https://user@accounts.google.com/token",
        "https://accounts.google.com:444/token",
        "https://accounts.google.com/token#fragment",
    ],
)
def test_provider_rejects_untrusted_endpoints(url: str) -> None:
    with pytest.raises(ValueError, match="untrusted provider endpoint"):
        provider().safe_url(url)


async def test_authorization_url_contains_oidc_and_pkce_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = provider()
    monkeypatch.setattr(
        adapter,
        "metadata",
        AsyncMock(
            return_value={"authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth"}
        ),
    )

    url = await adapter.authorization_url("state-value", attempt())
    query = parse_qs(urlsplit(url).query)

    assert query["client_id"] == ["client-id"]
    assert query["redirect_uri"] == ["https://api.example.com/callback"]
    assert query["state"] == ["state-value"]
    assert query["nonce"] == ["nonce-value"]
    assert query["code_challenge_method"] == ["S256"]
    assert "code_challenge" in query


@pytest.mark.parametrize(
    "metadata",
    [
        {"issuer": "https://evil.example", "code_challenge_methods_supported": ["S256"]},
        {
            "issuer": ISSUERS[ProviderName.GOOGLE],
            "code_challenge_methods_supported": ["plain"],
        },
    ],
)
async def test_discovery_rejects_wrong_issuer_or_missing_s256(
    monkeypatch: pytest.MonkeyPatch,
    metadata: dict[str, object],
) -> None:
    adapter = provider()
    monkeypatch.setattr(adapter, "document", AsyncMock(return_value=metadata))

    with pytest.raises(ValueError):
        await adapter.metadata()


class FakeTokenClient:
    def __init__(self, encoded: str) -> None:
        self.encoded = encoded

    async def __aenter__(self) -> "FakeTokenClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, **kwargs: object) -> httpx.Response:
        del kwargs
        return httpx.Response(
            status_code=200,
            json={"id_token": self.encoded, "access_token": "discard-me"},
            request=httpx.Request("POST", url),
        )


def signed_token(claim_changes: Mapping[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    key = generate_key("RSA", 2048, {"kid": "key-1"}, private=True)
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": ISSUERS[ProviderName.GOOGLE],
        "aud": "client-id",
        "exp": now + 300,
        "iat": now,
        "sub": "provider-subject",
        "nonce": "nonce-value",
        "email": "customer@example.com",
        "email_verified": True,
    }
    if claim_changes:
        claims.update(claim_changes)
    encoded = jwt.encode(
        {"alg": "RS256", "kid": "key-1"},
        claims,
        key,
        algorithms=["RS256"],
    )
    return encoded, {"keys": [key.as_dict(private=False)]}


async def exchange(
    monkeypatch: pytest.MonkeyPatch,
    *,
    claim_changes: Mapping[str, Any] | None = None,
    intent: str = "login",
) -> Identity:
    adapter = provider()
    encoded, jwks = signed_token(claim_changes)
    monkeypatch.setattr(
        adapter,
        "metadata",
        AsyncMock(
            return_value={
                "token_endpoint": "https://oauth2.googleapis.com/token",
                "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
            }
        ),
    )
    monkeypatch.setattr(adapter, "document", AsyncMock(return_value=jwks))
    monkeypatch.setattr(
        "ekumidayomi.auth.oidc.providers.httpx.AsyncClient",
        lambda **kwargs: FakeTokenClient(encoded),
    )
    return await adapter.exchange("authorization-code", attempt(intent=intent))


async def test_exchange_accepts_a_valid_signed_id_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = await exchange(monkeypatch)

    assert identity.provider is ProviderName.GOOGLE
    assert identity.subject == "provider-subject"
    assert identity.email == "customer@example.com"
    assert identity.email_verified is True


@pytest.mark.parametrize(
    "claim_changes",
    [
        {"iss": "https://evil.example"},
        {"aud": "another-client"},
        {"nonce": "another-nonce"},
        {"exp": 1},
        {"iat": 1},
        {"sub": ""},
        {"aud": ["client-id", "another-client"]},
        {"aud": ["client-id", "another-client"], "azp": "another-client"},
    ],
)
async def test_exchange_rejects_invalid_identity_claims(
    monkeypatch: pytest.MonkeyPatch,
    claim_changes: Mapping[str, Any],
) -> None:
    with pytest.raises(ExternalLoginFailedError):
        await exchange(monkeypatch, claim_changes=claim_changes)


async def test_provider_reauthentication_requires_fresh_auth_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ExternalLoginFailedError):
        await exchange(monkeypatch, intent="reauthenticate")

    identity = await exchange(
        monkeypatch,
        intent="reauthenticate",
        claim_changes={"auth_time": int(time.time())},
    )
    assert identity.auth_time is not None


async def test_exchange_rejects_a_signature_from_another_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = provider()
    encoded, _ = signed_token()
    another_key = generate_key("RSA", 2048, {"kid": "key-1"}, private=True)
    monkeypatch.setattr(
        adapter,
        "metadata",
        AsyncMock(
            return_value={
                "token_endpoint": "https://oauth2.googleapis.com/token",
                "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
            }
        ),
    )
    monkeypatch.setattr(
        adapter,
        "document",
        AsyncMock(return_value={"keys": [another_key.as_dict(private=False)]}),
    )
    monkeypatch.setattr(
        "ekumidayomi.auth.oidc.providers.httpx.AsyncClient",
        lambda **kwargs: FakeTokenClient(encoded),
    )

    with pytest.raises(ExternalLoginFailedError):
        await adapter.exchange("authorization-code", attempt())
