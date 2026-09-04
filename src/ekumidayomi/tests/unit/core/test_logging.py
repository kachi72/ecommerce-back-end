"""Structured logging tests."""

import json
import logging
import sys
from collections.abc import Iterator

import pytest

from ekumidayomi.core.logging import JsonLogFormatter, configure_logging
from ekumidayomi.core.observability import bind_request_id, reset_request_id


@pytest.fixture
def application_logger() -> Iterator[logging.Logger]:
    """Restore global logger state after each configuration test."""
    logger = logging.getLogger("ekumidayomi")
    handlers = logger.handlers[:]
    level = logger.level
    propagate = logger.propagate
    try:
        yield logger
    finally:
        logger.handlers[:] = handlers
        logger.setLevel(level)
        logger.propagate = propagate


def make_record(*, request_id: str | None = None) -> logging.LogRecord:
    """Build a deterministic record with safe and deliberately unsafe extras."""
    record = logging.LogRecord(
        name="ekumidayomi.http",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request_completed",
        args=(),
        exc_info=None,
    )
    record.created = 1_767_268_800.0
    record.__dict__.update(
        {
            "method": "GET",
            "route": "/products/{product_id}",
            "status_code": 200,
            "password": "must-not-appear",
            "authorization": "Bearer must-not-appear",
        }
    )
    if request_id is not None:
        record.__dict__["request_id"] = request_id
    return record


def test_json_formatter_emits_stable_allowlisted_fields() -> None:
    formatter = JsonLogFormatter(
        service_name="ekumidayomi-api",
        environment="test",
    )
    token = bind_request_id("context-request-123")
    try:
        payload = json.loads(formatter.format(make_record()))
    finally:
        reset_request_id(token)

    assert payload == {
        "timestamp": "2026-01-01T12:00:00+00:00",
        "level": "info",
        "logger": "ekumidayomi.http",
        "service": "ekumidayomi-api",
        "environment": "test",
        "message": "request_completed",
        "request_id": "context-request-123",
        "method": "GET",
        "route": "/products/{product_id}",
        "status_code": 200,
    }


def test_json_formatter_prefers_an_explicit_record_request_id() -> None:
    formatter = JsonLogFormatter(
        service_name="ekumidayomi-api",
        environment="test",
    )
    token = bind_request_id("context-request")
    try:
        payload = json.loads(formatter.format(make_record(request_id="record-request")))
    finally:
        reset_request_id(token)

    assert payload["request_id"] == "record-request"


def test_json_formatter_omits_arbitrary_extras_and_exception_payloads() -> None:
    formatter = JsonLogFormatter(
        service_name="ekumidayomi-api",
        environment="test",
    )
    record = make_record()
    try:
        raise RuntimeError("database-password=private")
    except RuntimeError:
        record.exc_info = sys.exc_info()

    encoded = formatter.format(record)
    payload = json.loads(encoded)

    assert "password" not in payload
    assert "authorization" not in payload
    assert "exception" not in payload
    assert "must-not-appear" not in encoded
    assert "database-password" not in encoded


def test_configure_logging_is_idempotent_and_honours_json_settings(
    application_logger: logging.Logger,
) -> None:
    for _ in range(2):
        configure_logging(
            service_name="ekumidayomi-api",
            environment="test",
            level="ERROR",
            output_format="json",
        )

    assert len(application_logger.handlers) == 1
    assert isinstance(application_logger.handlers[0].formatter, JsonLogFormatter)
    assert application_logger.level == logging.ERROR
    assert application_logger.propagate is False


def test_configure_logging_supports_human_readable_console_output(
    application_logger: logging.Logger,
) -> None:
    configure_logging(
        service_name="ekumidayomi-api",
        environment="development",
        level="DEBUG",
        output_format="console",
    )

    formatter = application_logger.handlers[0].formatter
    assert formatter is not None
    assert not isinstance(formatter, JsonLogFormatter)
    assert application_logger.level == logging.DEBUG
