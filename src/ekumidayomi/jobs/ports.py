"""Provider-neutral background-worker contracts."""

from collections.abc import Mapping
from typing import Protocol


class JobHandler(Protocol):
    """Handle one job payload without depending on a worker vendor."""

    async def __call__(
        self,
        payload: Mapping[str, object],
    ) -> Mapping[str, object] | None: ...


class Worker(Protocol):
    """Run at most one polling and execution cycle."""

    async def run_once(self) -> bool: ...
