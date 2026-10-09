# Auth Email Delivery Runbook

## Before enabling the worker

- Verify the sending domain in Resend and install its required DNS records through the domain owner. Keep Google Workspace MX records for business inboxes; do not replace them merely to send through Resend.
- Provision a scoped sending API key. Inject it and a random fingerprint key through the secret manager. Keep the fingerprint key, sender address and existing template text stable until queued deliveries finish.
- Resend keys last 24 hours. Automatic delivery age is at most 23 hours (default one hour), further limited by challenge expiry. A retry preserves the event ID/key; a user-requested new challenge has a new ID/key.
- The worker receives settings once from the core root. No SMTP fallback is permitted: switching providers after an uncertain result would bypass deduplication.
- Stop old auth workers before applying the owner-generated migration. Add the lease/fingerprint/receipt/budget/deadline columns and worker-control table. Backfill old auth processing rows to retryable failed state only during this stopped-worker cutover. Never reset already-recorded lifetime attempts.
- Run the unit and PostgreSQL checks, then a controlled Resend sandbox submission with a dedicated test recipient. Do not use real customer OTPs in checks or logs.

## Commands

Run from the backend repository root after implementing all units:

```powershell
uv run python -m ekumidayomi.auth.delivery_worker run
uv run python -m ekumidayomi.auth.delivery_worker run --once
uv run python -m ekumidayomi.auth.delivery_worker status
uv run python -m ekumidayomi.auth.delivery_worker replay --message-id <OUTBOX_UUID> --reason transient_resolved
uv run python -m ekumidayomi.auth.delivery_worker resume
```

The replay/resume commands require privileged deployment access to the database and secrets; do not expose them directly to HTTP users. Use deployment access logs to identify the human operator. The database audit actor is SYSTEM, with a bounded reason and target—not a caller-supplied admin identity.

## Supervision and shutdown

- Deploy the command as a separate managed process/container, with restart-on-failure and a restart delay (for example 10 seconds).
- Supply a shutdown grace period of at least 60 seconds. SIGTERM stops claiming new messages and lets current bounded work drain. A forced kill leaves a lease for recovery.
- A paused worker continues polling and reporting a heartbeat but claims no new work. Restarts do not clear the durable pause. Correct configuration before privileged resume.
- Auth claims expire after 120 seconds by default; preparation is bounded to 10 seconds, submission to 20 seconds, each database context to 15 seconds. Do not attach long-running campaign jobs without reviewing these limits and renewal semantics.
- Poll and alert on the status report every 30 seconds. The implementation does not create a scheduler or external alert integration automatically.

## Recovery decisions

- Crash before submission: an expired lease can be reclaimed; attempts are not reset.
- Provider accepted but final commit failed: reclaim with the same event and recipient key; Resend returns the existing submission result within its window.
- Partial recipients: committed receipts skip accepted indexes. Uncommitted receipts are recovered through provider deduplication.
- Temporary outcome: capped backoff with jitter, respecting a bounded numeric Retry-After.
- Malformed/permanent outcome: dead status; inspect and fix the cause. Do not repeatedly schedule it.
- Credential/quota/key-content conflict: blocked status, persistent group pause for configuration failures. Restore the original content/key configuration where required; do not erase fingerprints to force a conflicting retry.
- Unknown outcome with an exhausted budget/deadline: uncertain status; inspect provider records before any new delivery decision. The CLI intentionally refuses uncertain or expired replay.
- Expired/consumed/superseded auth challenge: no further send is initiated. An already accepted email cannot be recalled; challenge verification remains authoritative.
- Dead/blocked replay: recheck domain eligibility and unchanged fingerprint, preserve receipts/key/deadline/attempt history, and grant at most three additional attempts up to a lifetime cap of 100. Replay does not automatically resume a paused group.
- An earlier terminal event blocks later events for the same aggregate unless it was successfully processed or intentionally skipped. Investigate rather than bypass ordered business transitions.
- Existing pre-cutover messages may already have been submitted through SMTP. Provider keys cannot retroactively deduplicate those submissions. Prefer letting old challenges expire before activating the new sender.

## Alerts and privacy

- Page/notify for oldest due auth work over 60 seconds, missing heartbeat over 180 seconds, any expired claims, paused groups and new dead/uncertain messages.
- Track delivery_result logs by bounded outcome/result_code, not event IDs as metric labels. Message IDs are safe log correlation fields; recipients, content, raw provider responses and credentials are forbidden.
- Provider_accepted means accepted for submission, not delivered to an inbox. Bounce/delivery webhooks and campaign consent/suppression remain separate later-domain work.
- Full request/response tracing and HTTP wire debug logging must remain disabled. Do not print settings or exception tracebacks containing request objects.

## Release evidence

Record unit, mypy, lint, migrated PostgreSQL crash/concurrency results and the controlled provider check. Exercise actual supervisor restart and alert routing before production exposure. S2-010 must not accept a Markdown syntax check as implementation evidence.

## Provider references

- [Idempotency contract](https://resend.com/docs/dashboard/emails/idempotency-keys)
- [Send email API](https://resend.com/docs/api-reference/emails/send-email)
- [Error classification](https://resend.com/docs/api-reference/errors)

Provider contracts checked on 2026-09-15. Verify again before deployment.
