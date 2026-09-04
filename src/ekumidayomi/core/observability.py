"""Provider-neutral observability contracts and request context."""

from abc import abstractmethod
from collections.abc import Mapping
from contextvars import ContextVar, Token
from typing import Protocol

type MetricLabels = Mapping[str, str]
type TraceAttribute = bool | float | int | str
type TraceAttributes = Mapping[str, TraceAttribute]

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)


class Metrics(Protocol):
    """Metrics operations used by the application layer."""

    @abstractmethod
    def increment(self, name: str, *, labels: MetricLabels | None = None) -> None:
        """Increment a counter."""
        raise NotImplementedError

    @abstractmethod
    def observe(
        self,
        name: str,
        value: float,
        *,
        labels: MetricLabels | None = None,
    ) -> None:
        """Record a measured value."""
        raise NotImplementedError


class NoOpMetrics:
    """Default metrics adapter used when no exporter is configured."""

    def increment(self, name: str, *, labels: MetricLabels | None = None) -> None:
        """Discard a counter increment when no metrics exporter is configured."""
        return None

    def observe(self, name: str, value: float, *, labels: MetricLabels | None = None) -> None:
        """Discard a measurement when no metrics exporter is configured."""
        return None


class Tracer(Protocol):
    """Tracing operation used until a concrete provider adapter is selected."""

    @abstractmethod
    def annotate(self, name: str, *, attributes: TraceAttributes | None = None) -> None:
        """Attach safe, low-cardinality attributes to the current operation."""
        raise NotImplementedError


class NoOpTracer:
    """Default tracing adapter used when no exporter is configured."""

    def annotate(
        self,
        name: str,
        *,
        attributes: TraceAttributes | None = None,
    ) -> None:
        """Discard trace attributes when no tracing exporter is configured."""
        return None


def bind_request_id(value: str) -> Token[str | None]:
    """Bind a request ID to the current asynchronous context."""
    return request_id_context.set(value)


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the context that existed before request processing."""
    request_id_context.reset(token)
