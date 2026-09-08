"""Project configuration dependencies bound to the current application instance."""

from typing import Annotated, cast

from fastapi import Depends, Request

from ekumidayomi.auth.settings import AuthSettings
from ekumidayomi.core.settings import Settings


def get_request_settings(request: Request) -> Settings:
    """Return the same root settings object used to construct this application."""
    return cast(Settings, request.app.state.settings)


def get_auth_settings(
    settings: Annotated[Settings, Depends(get_request_settings)],
) -> AuthSettings:
    """Project the auth group without loading or caching another settings object."""
    return settings.auth
