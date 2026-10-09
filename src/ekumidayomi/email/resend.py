"""Resend HTTP adapter; no hidden retries,redirects, raw error logs, or database I/O."""

import hashlib
import hmac
import json
from collections.abc import Mapping
from uuid import UUID

import httpx

from ekumidayomi.email.ports import EmailRequest, EmailSubmission
from ekumidayomi.email.schemas import OutgoingEmail
from ekumidayomi.email.settings import ResendSettings
from ekumidayomi.outbox.outcomes import DeliveryOutcome, OutcomeKind


class ResendEmailSender:
    def __init__(self, settings: ResendSettings, client: httpx.AsyncClient) -> None:
        self.settings = settings.model_copy(deep=True)
        self.client = client

    def prepare(self, message: OutgoingEmail) -> EmailSubmission:
        snapshot = OutgoingEmail.model_validate(message.model_dump())
        requests = []
        for index, address in enumerate(snapshot.recipients):
            body: dict[str, object] = {
                "from": str(self.settings.sender),
                "to": [str(address)],
                "subject": snapshot.subject,
                "text": snapshot.text_body,
            }
            if snapshot.html_body is not None:
                body["html"] = snapshot.html_body
            wire = json.dumps(
                body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
            requests.append(EmailRequest(f"email/{snapshot.delivery_id}/{index}", wire))

        canonical = b"".join(len(item.body).to_bytes(8, "big") + item.body for item in requests)
        fingerprint = hmac.new(
            self.settings.fingerprint_key.get_secret_value().encode(), canonical, hashlib.sha256
        ).hexdigest()
        return EmailSubmission(tuple(requests), fingerprint)

    async def send(
        self, submission: EmailSubmission, completed: Mapping[str, str]
    ) -> DeliveryOutcome:
        receipts = dict(completed)
        for index, request in enumerate(submission.requests):
            if str(index) in receipts:
                continue
            try:
                async with self.client.stream(
                    "POST",
                    "https://api.resend.com/emails",
                    content=request.body,
                    headers={
                        "Authorization": f"Bearer {self.settings.api_key.get_secret_value()}",
                        "Idempotency-Key": request.key,
                        "Content-Type": "application/json",
                    },
                    timeout=self.settings.timeout_seconds,
                    follow_redirects=False,
                ) as response:
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 16384:
                            return DeliveryOutcome(
                                OutcomeKind.UNCERTAIN,
                                "provider_response_invalid",
                                receipts=receipts,
                            )
                    try:
                        document = json.loads(data)
                    except (ValueError, UnicodeError):
                        document = {}
                    if not isinstance(document, dict):
                        document = {}

                    if response.status_code in (200, 201):
                        try:
                            provider_id = str(UUID(str(document.get("id", ""))))
                        except ValueError:
                            return DeliveryOutcome(
                                OutcomeKind.UNCERTAIN,
                                "provider_response_invalid",
                                receipts=receipts,
                            )
                        receipts[str(index)] = provider_id
                        continue

                    name = document.get("name")
                    if response.status_code in (401, 403) or name in (
                        "daily_quota_exceeded",
                        "monthly_quota_exceeded",
                    ):
                        return DeliveryOutcome(
                            OutcomeKind.BLOCKED, "provider_configuration", receipts=receipts
                        )
                    if name == "invalid_idempotent_request":
                        return DeliveryOutcome(
                            OutcomeKind.BLOCKED, "provider_key_conflict", receipts=receipts
                        )
                    if response.status_code == 429 or (
                        response.status_code == 409 and name == "concurrent_idempotent_requests"
                    ):
                        raw_delay = response.headers.get("Retry-After", "")
                        delay = (
                            min(int(raw_delay), 3600)
                            if raw_delay.isdecimal() and len(raw_delay) < 8
                            else 60
                        )
                        return DeliveryOutcome(OutcomeKind.RETRY, "provider_busy", delay, receipts)
                    if response.status_code >= 500 or response.status_code == 408:
                        return DeliveryOutcome(
                            OutcomeKind.UNCERTAIN, "provider_unavailable", receipts=receipts
                        )
                    return DeliveryOutcome(
                        OutcomeKind.PERMANENT, "provider_request_rejected", receipts=receipts
                    )
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
                return DeliveryOutcome(OutcomeKind.RETRY, "provider_connection", receipts=receipts)
            except httpx.HTTPError:
                return DeliveryOutcome(
                    OutcomeKind.UNCERTAIN, "provider_result_unknown", receipts=receipts
                )
        return DeliveryOutcome(OutcomeKind.ACCEPTED, "provider_accepted", receipts=receipts)
