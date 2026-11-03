"""Pinned OIDC discovery, authorization-code exchange, and ID-token validation."""

import asyncio
import base64
import hashlib
import json
import time
from typing import Any, cast
from urllib.parse import urlencode, urlsplit

import httpx
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet, KeySetSerialization
from joserfc.jwt import JWTClaimsRegistry

from ekumidayomi.auth.oidc.contracts import Attempt, Identity, Provider
from ekumidayomi.auth.oidc.settings import ISSUERS, ProviderConfig, ProviderName
from ekumidayomi.users.errors import ExternalLoginFailedError

_ALLOWED_HOSTS: dict[ProviderName, frozenset[str]] = {
    ProviderName.GOOGLE: frozenset(
        {"accounts.google.com", "oauth2.googleapis.com", "www.googleapis.com"}
    ),
    ProviderName.YAHOO: frozenset({"api.login.yahoo.com"}),
}
_DOCUMENT_LIMIT = 262_144
_TOKEN_RESPONSE_LIMIT = 65_536
_ID_TOKEN_LIMIT = 32_768


def challenge(verifier: str) -> str:
    """Return the unpadded RFC 7636 S256 challenge for a verifier."""

    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class OidcProvider(Provider):
    """Validate one provider without trusting provider-controlled endpoint URLs."""

    def __init__(self, name: ProviderName, config: ProviderConfig, timeout: float) -> None:
        self.name = ProviderName(name)
        self.config = config
        self.timeout = timeout
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    def safe_url(self, value: object) -> str:
        """Accept HTTPS endpoints only on the provider's pinned host allowlist."""

        if not isinstance(value, str):
            raise ValueError("missing provider endpoint")
        url = urlsplit(value)
        if (
            url.scheme != "https"
            or url.hostname not in _ALLOWED_HOSTS[self.name]
            or url.username
            or url.password
            or url.fragment
            or url.port not in {None, 443}
        ):
            raise ValueError("untrusted provider endpoint")
        return value

    async def document(self, url: str) -> dict[str, Any]:
        """Fetch and briefly cache a bounded provider JSON document."""

        self.safe_url(url)
        async with self._lock:
            cached = self._cache.get(url)
            if cached and cached[0] > time.monotonic():
                return cached[1]
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    body = bytearray()
                    async for part in response.aiter_bytes():
                        body.extend(part)
                        if len(body) > _DOCUMENT_LIMIT:
                            raise ValueError("provider document too large")
            value = json.loads(body)
            if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
                raise ValueError("invalid provider document")
            document = cast(dict[str, Any], value)
            self._cache[url] = (time.monotonic() + 300, document)
            return document

    async def metadata(self) -> dict[str, Any]:
        """Return discovery metadata after issuer and PKCE validation."""

        value = await self.document(ISSUERS[self.name] + "/.well-known/openid-configuration")
        if value.get("issuer") != ISSUERS[self.name]:
            raise ValueError("issuer mismatch")
        supported = value.get("code_challenge_methods_supported", [])
        if (
            not isinstance(supported, list)
            or not all(isinstance(method, str) for method in supported)
            or ("S256" not in supported and not self.config.pkce_verified)
        ):
            raise ValueError("S256 support is not established")
        return value

    async def authorization_url(self, state: str, attempt: Attempt) -> str:
        """Build a provider authorization URL with state, nonce, and PKCE."""

        try:
            metadata = await self.metadata()
            params = {
                "client_id": self.config.client_id,
                "redirect_uri": attempt.redirect_uri,
                "response_type": "code",
                "scope": "openid email profile",
                "state": state,
                "nonce": attempt.nonce,
                "code_challenge_method": "S256",
                "code_challenge": challenge(attempt.verifier),
            }
            if attempt.intent == "reauthenticate":
                params["max_age"] = "0"
            return self.safe_url(metadata.get("authorization_endpoint")) + "?" + urlencode(params)
        except (httpx.HTTPError, UnicodeError, ValueError, KeyError, TypeError):
            raise ExternalLoginFailedError() from None

    async def exchange(self, code: str, attempt: Attempt) -> Identity:
        """Exchange a code and return only cryptographically verified identity claims."""

        try:
            metadata = await self.metadata()
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
                response = await client.post(
                    self.safe_url(metadata.get("token_endpoint")),
                    auth=httpx.BasicAuth(
                        self.config.client_id,
                        self.config.client_secret.get_secret_value(),
                    ),
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": attempt.redirect_uri,
                        "code_verifier": attempt.verifier,
                    },
                )
                response.raise_for_status()
                if len(response.content) > _TOKEN_RESPONSE_LIMIT:
                    raise ValueError("token response too large")
                token = response.json()
            if not isinstance(token, dict):
                raise ValueError("invalid token response")
            encoded = token.get("id_token")
            if not isinstance(encoded, str) or len(encoded) > _ID_TOKEN_LIMIT:
                raise ValueError("missing ID token")
            jwks_document = await self.document(self.safe_url(metadata.get("jwks_uri")))
            key_set = KeySet.import_key_set(cast(KeySetSerialization, jwks_document))
            token = jwt.decode(
                encoded,
                key_set,
                algorithms=["RS256"],
            )
            claims = token.claims
            JWTClaimsRegistry(
                leeway=30,
                iss={"essential": True, "value": ISSUERS[self.name]},
                aud={"essential": True, "value": self.config.client_id},
                exp={"essential": True},
                iat={"essential": True},
                sub={"essential": True},
                nonce={"essential": True, "value": attempt.nonce},
            ).validate(claims)
            audiences = claims["aud"]
            if not isinstance(audiences, str | list) or (
                isinstance(audiences, list)
                and not all(isinstance(audience, str) for audience in audiences)
            ):
                raise ValueError("invalid audience")
            if (
                (isinstance(audiences, list) and len(audiences) > 1) or "azp" in claims
            ) and claims.get("azp") != self.config.client_id:
                raise ValueError("authorized party mismatch")
            issued = claims["iat"]
            if (
                isinstance(issued, bool)
                or not isinstance(issued, int | float)
                or issued > time.time() + 30
                or issued < attempt.started_at - 60
            ):
                raise ValueError("issued-at outside this handshake")
            subject = claims["sub"]
            if not isinstance(subject, str) or not 1 <= len(subject) <= 255:
                raise ValueError("invalid subject")
            auth_time = claims.get("auth_time")
            if attempt.intent == "reauthenticate" and (
                isinstance(auth_time, bool)
                or not isinstance(auth_time, int)
                or auth_time < attempt.started_at - 30
                or auth_time > time.time() + 30
            ):
                raise ValueError("fresh provider authentication was not established")
            email = claims.get("email")
            return Identity(
                provider=self.name,
                subject=subject,
                email=email if isinstance(email, str) else None,
                email_verified=claims.get("email_verified") is True,
                auth_time=(
                    auth_time
                    if isinstance(auth_time, int) and not isinstance(auth_time, bool)
                    else None
                ),
            )
        except (
            httpx.HTTPError,
            JoseError,
            UnicodeError,
            ValueError,
            KeyError,
            TypeError,
        ):
            raise ExternalLoginFailedError() from None
