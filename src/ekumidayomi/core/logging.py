"""Privacy-safe structured logging configuration."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Final

from ekumidayomi.core.observability import request_id_context

_SAFE_EXTRA_FIELDS: Final[tuple[str, ...]] = (
    "method",
    "route",
    "status_code",
    "duration_ms",
    "outcome",
    "dependency",
    "exception_type",
)

type PAYLOAD_TYPES = bool | float | int | str | None


class JsonLogFormatter(logging.Formatter):
    """Render a stable  JSON log record."""

    def __init__(self, service_name: str, environment: str) -> None:
        super().__init__()
        self._service_name = service_name
        self._environment = environment

    def format(self, record: logging.LogRecord) -> str:
        """Serialize the record without arbitrary extras or exception payloads."""
        record_request_id = getattr(record, "request_id", None)
        request_id = (
            record_request_id if isinstance(record_request_id, str) else request_id_context.get()
        )
        payload: dict[str, PAYLOAD_TYPES] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "service": self._service_name,
            "environment": self._environment,
            "message": record.getMessage(),
            "request_id": request_id,
        }

        for field in _SAFE_EXTRA_FIELDS:
            value = getattr(record, field, None)
            if isinstance(value, bool | str | float | int):
                payload[field] = value

        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(
    *, service_name: str, environment: str, level: str, output_format: str
) -> None:
    """Configure the application logger deterministically."""
    handler = logging.StreamHandler()
    if output_format == "json":
        handler.setFormatter(JsonLogFormatter(service_name=service_name, environment=environment))
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s %(message)s",
            )
        )

    application_logger = logging.getLogger("ekumidayomi")
    application_logger.handlers[:] = [handler]
    application_logger.setLevel(level)
    application_logger.propagate = False
