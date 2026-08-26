"""ASGI entry point used by Uvicorn."""

from fastapi import FastAPI

from ekumidayomi import __version__
from ekumidayomi.api.v1.router import router as api_v1_router


def create_app() -> FastAPI:
    """Build the minimal application."""
    application = FastAPI(title="Ẹkúmidáyọ̀mí API", version=__version__)
    application.include_router(api_v1_router, prefix="/api/v1")
    return application



app = create_app()