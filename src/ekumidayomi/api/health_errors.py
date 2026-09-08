"""Stable readiness errors with bounded, non-sensitive dependency results."""

from http import HTTPStatus
from typing import Literal

from ekumidayomi.core.errors import DependencyUnavailableError


class ServiceNotReadyError(DependencyUnavailableError):
    """A required service dependency failed its readiness check."""

    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    code = "service_not_ready"
    message = "Service is not ready"

    def __init__(self, *, checks: dict[str, Literal["ok", "failed"]]) -> None:
        if set(checks) != {"postgresql", "redis"} or any(
            result not in {"ok", "failed"} for result in checks.values()
        ):
            raise ValueError("readiness checks require only known dependency outcomes")
        if "failed" not in checks.values():
            raise ValueError("a readiness error requires a failed dependency")
        super().__init__(details={"checks": checks})
