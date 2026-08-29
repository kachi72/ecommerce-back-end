"""Reusable test helper contexts."""

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from fastapi import FastAPI

Dependency = Callable[..., Any]


@contextmanager
def override_dependencies(
    app: FastAPI,
    overrides: Mapping[Dependency, Dependency],
) -> Iterator[None]:
    """Apply dependency overrides and restore the previous mapping afterward."""
    previous = app.dependency_overrides.copy()
    app.dependency_overrides.update(overrides)
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
