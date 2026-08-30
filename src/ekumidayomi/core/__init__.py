"""Shared application configuration, lifecycle, and value contracts."""

from ekumidayomi.core.errors import (
    ApplicationError,
    AuthenticationError,
    ConflictError,
    DependencyUnavailableError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)
from ekumidayomi.core.settings import AppEnvironment, Settings, get_settings
from ekumidayomi.core.types import (
    Currency,
    EntityId,
    Money,
    Page,
    PageRequest,
    new_entity_id,
    require_utc,
    serialize_entity_id,
    serialize_utc,
    utc_now,
)

__all__ = [
    "AppEnvironment",
    "ApplicationError",
    "AuthenticationError",
    "ConflictError",
    "Currency",
    "DependencyUnavailableError",
    "EntityId",
    "ForbiddenError",
    "Money",
    "NotFoundError",
    "Page",
    "PageRequest",
    "RateLimitError",
    "Settings",
    "ValidationError",
    "get_settings",
    "new_entity_id",
    "require_utc",
    "serialize_entity_id",
    "serialize_utc",
    "utc_now",
]
