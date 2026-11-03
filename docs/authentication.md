# Identity and authentication

Ẹkúmidáyọ̀mí uses opaque server-side sessions rather than application JWTs. PostgreSQL owns
credentials, user status, roles, session expiry and revocation. Redis is a cache and rate-limit
coordination service; a cache hit never replaces the durable authorization check.

## Browser integration

Deploy the frontend and API on same-site HTTPS origins. Configure exact browser origins through
`EKUMIDAYOMI_AUTH__ALLOWED_ORIGINS` and configure matching CORS origins through
`EKUMIDAYOMI_CORS_ORIGINS`. Wildcards and trailing slashes are rejected for authentication
origins. Browser requests include credentials.

Unsafe requests require a trusted `Origin` header. `SameSite=Lax` is defense in depth, not the
project's only CSRF control. Production session cookies use the `__Host-` prefix together with
`Secure`, `HttpOnly`, `SameSite=Lax` and `Path=/`; no session token is exposed to JavaScript.

Registration returns a generic challenge identifier. Verification submits that identifier, the
six-digit code and the initial password. Successful verification does not log the customer in;
the customer then signs in and receives a fresh session cookie. Password reset also returns a
generic initiation response, revokes all existing sessions after completion and does not create a
new logged-in session.

## Stable errors and enumeration resistance

Identity business errors are declared in `users/errors.py`. Each named error owns its stable HTTP
status, code and safe message. The shared API handler renders those attributes directly. Pydantic
validation, parser failures and programmer-contract errors remain framework or standard Python
exceptions rather than business errors.

Authentication, challenge and password-reset failures deliberately avoid exposing whether an
email address exists. Error details must never contain passwords, one-time codes, session secrets,
provider responses or account-existence flags. Rate-limit errors expose only a validated
`Retry-After` value.

## Password policy

Passwords are 15–128 characters. There is no mandatory uppercase, lowercase, number or symbol
composition rule. Spaces, Unicode and single-case passphrases are permitted. The submitted value
is not silently trimmed or normalized.

New registration, password reset and first-admin bootstrap reject locally common passwords,
single-character repetition and passwords present in the HIBP Pwned Passwords service. Argon2id
is the credential hashing algorithm; it is not a password-strength check. Existing login and local
Argon2id rehash do not call the breach service.

HIBP screening sends only the first five characters of a SHA-1 digest and requests padded range
responses. It never sends the password, full digest, email or account data. Timeouts, malformed
responses and transport failures fail closed: no new credential is stored, no challenge is
consumed and the customer receives a retryable service-unavailable error. Keep HTTP client debug
logging disabled and never log the range URL, prefix or response body.

## Challenge-key rotation

Configure `EKUMIDAYOMI_AUTH__CHALLENGE_KEYS` as a JSON mapping of key versions to independent
random secrets of at least 32 characters. Set `EKUMIDAYOMI_AUTH__ACTIVE_CHALLENGE_KEY` to the
version used for new challenges. Retain old keys until every challenge and queued delivery that
uses them has expired. Emergency key removal intentionally invalidates affected challenges.

Challenges are purpose-bound, expire quickly, allow a bounded number of attempts and are consumed
once under a PostgreSQL lock. Registration and password-reset challenges cannot be exchanged
across purposes.

## Email delivery and recovery

Transactional identity email uses Resend over HTTPS; there is no SMTP fallback. Configure:

- `EKUMIDAYOMI_RESEND__API_KEY`
- `EKUMIDAYOMI_RESEND__SENDER`
- `EKUMIDAYOMI_RESEND__FINGERPRINT_KEY`
- `EKUMIDAYOMI_RESEND__TIMEOUT_SECONDS`

Run the supervised worker separately from the API:

```powershell
uv run python -m ekumidayomi.auth.delivery_worker run
uv run python -m ekumidayomi.auth.delivery_worker run --once
uv run python -m ekumidayomi.auth.delivery_worker status
```

Recovery commands are privileged operational actions:

```powershell
uv run python -m ekumidayomi.auth.delivery_worker replay --message-id <OUTBOX_UUID> --reason transient_resolved
uv run python -m ekumidayomi.auth.delivery_worker resume
```

Delivery uses leases, stable provider idempotency keys, persisted receipts and classified retry
outcomes. Provider acceptance is not proof of inbox delivery. Follow
{doc}`runbooks/auth-email-delivery` for cutover, replay, pause, alert and uncertain-delivery
procedures.

## Administration and incident response

Create the first administrator only after confirming mailbox ownership out of band:

```powershell
uv run python -m ekumidayomi.auth.bootstrap --email owner@example.com --email-verified
```

The command prompts for the password without placing it in shell history. Later administrator
changes use the authenticated administration API. PostgreSQL serializes administrator membership
changes so concurrent requests cannot remove the final active, verified administrator.

During an account incident, deactivate the user or revoke all sessions through an authorized
operation. Deleting a Redis cache key is not durable revocation. Investigate request IDs and
sanitized audit records rather than request bodies or authentication material.

## External identity providers

Google and Yahoo use authorization-code OIDC with S256 PKCE. Both providers are disabled by
default. Enabling one requires its client ID, client secret and exact HTTPS callback URI. Yahoo
also requires `PKCE_VERIFIED=true`; keep it disabled until a controlled provider test proves that
Yahoo enforces the S256 verifier and returns the required claims.

The login attempt is stored once in Redis and bound to a dedicated HttpOnly browser cookie. The
callback consumes the attempt atomically and validates the state, provider, browser binding,
nonce, RS256 signature, issuer, audience, authorized party, expiry, issued-at time and subject.
Provider reauthentication additionally requires a fresh `auth_time`. Redis failure fails closed.

Provider tokens are discarded after validation. A successful provider login creates the same
revocable PostgreSQL session and opaque browser cookie as password login. Provider claims never
assign roles. A matching email address never auto-links an existing account: linking is an
authenticated, recently reauthenticated action. Unlinking cannot remove the final usable login
method.

Configure Google with:

- `EKUMIDAYOMI_AUTH__OIDC__GOOGLE__ENABLED`
- `EKUMIDAYOMI_AUTH__OIDC__GOOGLE__CLIENT_ID`
- `EKUMIDAYOMI_AUTH__OIDC__GOOGLE__CLIENT_SECRET`
- `EKUMIDAYOMI_AUTH__OIDC__GOOGLE__REDIRECT_URI`

Yahoo uses the equivalent `EKUMIDAYOMI_AUTH__OIDC__YAHOO__*` names plus
`EKUMIDAYOMI_AUTH__OIDC__YAHOO__PKCE_VERIFIED`. Configure the provider console callback to the
exact value supplied to the application. Do not add wildcard callbacks.

Authorization codes arrive in callback query strings. Disable Uvicorn's access logger in the
production process (for example, `--no-access-log`) and configure the reverse proxy and edge not
to record query strings. Retain the application's structured request log, which records the route
template and request ID without authentication query values.

## Privacy-safe telemetry

Never log passwords, one-time codes, cookies, authorization headers, email bodies, provider tokens
or raw external responses. Disable query-string access logging before enabling future OIDC
callbacks. Metrics use bounded operation and outcome labels; user IDs, emails, session IDs and
message IDs must not become metric labels. Sensitive responses use `Cache-Control: no-store`.

## Verification

Run the unchanged project gates:

```powershell
just lint
just format-check
just typecheck
just test
just coverage
uv run coverage report --include="src\\ekumidayomi\\auth\\*,src\\ekumidayomi\\users\\*" --fail-under=95
just migration-integrity
just docs-check
```

The identity gate additionally covers an in-process customer journey, challenge denial and replay
behavior, session revocation, customer/admin separation, address ownership, independent-connection
administrator and verification races, real-Redis rate-limit atomicity, OIDC state/browser replay,
signed ID-token claim validation and external-identity lifecycle rules.

## References

- [OWASP authentication guidance](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
- [OWASP password-reset guidance](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html)
- [HIBP Pwned Passwords API](https://haveibeenpwned.com/API/v3#PwnedPasswords)
- [Resend idempotency keys](https://resend.com/docs/dashboard/emails/idempotency-keys)

