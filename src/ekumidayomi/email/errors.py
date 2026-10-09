"""Safe transport failures shared by email-producing domains."""

from http import HTTPStatus

from ekumidayomi.core.errors import DependencyUnavailableError


class EmailDeliveryError(DependencyUnavailableError):
    """SMTP submission failed or its outcome could not be confirmed."""

    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    code = "email_delivery_failed"
    message = "Email delivery is temporary unavailable."
