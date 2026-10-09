from uuid import uuid4

import pytest
from pydantic import ValidationError

from ekumidayomi.email.schemas import OutgoingEmail


def test_domain_neutral_message_hides_content_in_repr() -> None:
    message = OutgoingEmail(
        delivery_id=uuid4(),
        recipients=["customer@example.com"],
        subject="Order received",
        text_body="Private order details",
        html_body="<p>Private order details</p>",
    )
    assert message.recipients == ["customer@example.com"]
    assert message.text_body == "Private order details"
    assert "customer@example.com" not in repr(message)
    assert "Private order details" not in repr(message)
    for attribute in ("subject", "text_body"):
        with pytest.raises(ValidationError):
            setattr(message, attribute, "Changed")


@pytest.mark.parametrize("subject", ["", " ", "a" * 201, "Hello\r\nBcc: other", "Hello\x00"])
def test_invalid_headers_are_rejected(subject: str) -> None:
    with pytest.raises(ValidationError):
        OutgoingEmail(
            delivery_id=uuid4(),
            recipients=["customer@example.com"],
            subject=subject,
            text_body="Message",
        )


@pytest.mark.parametrize("recipient", ["not-an-email", "a@example.com\r\nBcc: b@example.com"])
def test_invalid_recipient_is_rejected(recipient: str) -> None:
    with pytest.raises(ValidationError):
        OutgoingEmail(
            delivery_id=uuid4(),
            recipients=[recipient],
            subject="Subject",
            text_body="Message",
        )


def test_message_limits_and_unknown_fields() -> None:
    data = {
        "delivery_id": str(uuid4()),
        "recipients": ["customer@example.com"],
        "subject": "Subject",
        "text_body": "Message",
    }
    for override in (
        {"text_body": ""},
        {"text_body": "x" * 131073},
        {"html_body": "x" * 262145},
        {"delivery_id": "bad-id"},
        {"bcc": "hidden@example.com"},
    ):
        with pytest.raises(ValidationError):
            OutgoingEmail.model_validate(data | override)


@pytest.mark.parametrize(
    "recipients",
    [
        [],
        ["customer@example.com", "customer@example.com"],
        ["Customer@example.com", "customer@example.com"],
        [f"customer{index}@example.com" for index in range(101)],
        "customer@example.com",
    ],
)
def test_recipient_batch_validation(recipients: object) -> None:
    with pytest.raises(ValidationError):
        OutgoingEmail.model_validate(
            {
                "delivery_id": str(uuid4()),
                "recipients": recipients,
                "subject": "Subject",
                "text_body": "Message",
            }
        )


def test_bulk_recipient_list_is_supported() -> None:
    message = OutgoingEmail(
        delivery_id=uuid4(),
        recipients=["one@example.com", "two@example.com"],
        subject="Newsletter",
        text_body="Shared content",
    )
    assert message.recipients == ["one@example.com", "two@example.com"]
