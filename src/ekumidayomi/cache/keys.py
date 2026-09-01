"""Owned Redis cache-key construction."""

import re
from dataclasses import dataclass

_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_APPLICATION_NAMESPACE = "ekumidayomi"


@dataclass(frozen=True, slots=True)
class CacheKey:
    """A bounded cache key with explicit environment, owner, and schema version."""

    environment: str
    owner: str
    version: int
    scope: str
    identifier: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.version, bool)
            or not isinstance(self.version, int)
            or not 1 <= self.version <= 999
        ):
            raise ValueError("version must be an integer between 1 and 999")
        for name in ("environment", "owner", "scope", "identifier"):
            value = getattr(self, name)
            if not isinstance(value, str) or _SEGMENT.fullmatch(value) is None:
                raise ValueError(f"unsafe cache key segment: {name}")

    def render(self) -> str:
        """Render a cluster-compatible key for one versioned cache value."""

        slot = f"{self.environment}:{self.owner}:{self.scope}:{self.identifier}"
        return f"{_APPLICATION_NAMESPACE}:{{{slot}}}:v{self.version}"

    def lock_key(self) -> str:
        """Return a lock key in the same Redis Cluster slot as the value."""

        return f"{self.render()}:lock"
