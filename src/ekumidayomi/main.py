"""ASGI entry point used by Uvicorn."""

from ekumidayomi.core.application import create_app

app = create_app()

__all__ = ["app", "create_app"]
