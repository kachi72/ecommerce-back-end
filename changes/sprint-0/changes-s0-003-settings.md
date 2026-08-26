# S0-003 — Add Typed Application Settings

## Summary

Load all environment configuration through one cached Pydantic settings object and reject unsafe production or test configuration.

## Detailed Explanation

Application code must not read environment variables directly. `Settings` owns parsing and validation for the application, PostgreSQL, Redis, HTTP middleware, and startup behavior. Production rejects debug mode, wildcard hosts/origins, placeholder secrets, and disabled secure cookies. Test configuration must use a database distinct from development.

## Target File: `src/ekumidayomi/core/settings.py`

## Proposed Change

Create the file with:

```python
"""Typed application configuration."""

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnvironment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Configuration loaded exclusively from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="EKUMIDAYOMI_",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: AppEnvironment = AppEnvironment.DEVELOPMENT
    app_name: str = "Ẹkúmidáyọ̀mí API"
    debug: bool = False
    api_prefix: str = "/api/v1"

    database_url: str = "postgresql+asyncpg://ekumidayomi:development-only@localhost:5432/ekumidayomi"
    test_database_url: str = "postgresql+asyncpg://ekumidayomi:test-only@localhost:5433/ekumidayomi_test"
    database_pool_size: int = Field(default=10, ge=1, le=50)
    database_max_overflow: int = Field(default=10, ge=0, le=50)
    database_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=30)

    redis_url: str = "redis://localhost:6379/0"
    redis_connect_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    redis_operation_timeout_seconds: float = Field(default=2.0, gt=0, le=30)

    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    cors_origins: list[str] = []
    secure_cookies: bool = False
    secret_key: SecretStr = SecretStr("development-only-change-me")
    check_dependencies_on_startup: bool = True

    @property
    def active_database_url(self) -> str:
        """Return the database URL for the active environment."""
        if self.app_env is AppEnvironment.TEST:
            return self.test_database_url
        return self.database_url

    @model_validator(mode="after")
    def validate_environment_safety(self) -> "Settings":
        if self.app_env is AppEnvironment.TEST and self.database_url == self.test_database_url:
            raise ValueError("test_database_url must differ from database_url")

        if self.app_env is AppEnvironment.PRODUCTION:
            unsafe_secrets = {
                "development-only-change-me",
                "change-me",
                "changeme",
                "secret",
            }
            if self.debug:
                raise ValueError("debug must be disabled in production")
            if not self.secure_cookies:
                raise ValueError("secure_cookies must be enabled in production")
            if "*" in self.allowed_hosts:
                raise ValueError("wildcard allowed_hosts are forbidden in production")
            if "*" in self.cors_origins:
                raise ValueError("wildcard cors_origins are forbidden in production")
            if not self.allowed_hosts:
                raise ValueError("allowed_hosts must not be empty in production")
            if self.secret_key.get_secret_value().lower() in unsafe_secrets:
                raise ValueError("a non-placeholder secret_key is required in production")

        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide validated settings instance."""
    return Settings()
```

## Target File: `src/ekumidayomi/tests/unit/core/test_settings.py`

## Proposed Change

Create the directory and file with:

```python
"""Settings validation tests."""

import pytest
from pydantic import ValidationError

from ekumidayomi.core.settings import AppEnvironment, Settings


def test_test_database_must_differ_from_development_database() -> None:
    with pytest.raises(ValidationError, match="must differ"):
        Settings(
            app_env=AppEnvironment.TEST,
            database_url="postgresql+asyncpg://user:pass@db/app",
            test_database_url="postgresql+asyncpg://user:pass@db/app",
        )


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"debug": True}, "debug"),
        ({"secure_cookies": False}, "secure_cookies"),
        ({"allowed_hosts": ["*"]}, "wildcard allowed_hosts"),
        ({"cors_origins": ["*"]}, "wildcard cors_origins"),
        ({"secret_key": "change-me"}, "non-placeholder secret_key"),
    ],
)
def test_production_rejects_unsafe_values(
    override: dict[str, object],
    message: str,
) -> None:
    values: dict[str, object] = {
        "app_env": AppEnvironment.PRODUCTION,
        "allowed_hosts": ["api.example.com"],
        "secure_cookies": True,
        "secret_key": "a-production-secret-provided-by-the-secret-store",
    }
    values.update(override)

    with pytest.raises(ValidationError, match=message):
        Settings.model_validate(values)


def test_active_database_url_uses_test_database_in_test_environment() -> None:
    settings = Settings(app_env=AppEnvironment.TEST)

    assert settings.active_database_url == settings.test_database_url
```

## Target File: `src/ekumidayomi/core/__init__.py`

## Proposed Change

Replace its package-only content with:

```python
"""Shared application configuration and lifecycle utilities."""

from ekumidayomi.core.settings import AppEnvironment, Settings, get_settings

__all__ = ["AppEnvironment", "Settings", "get_settings"]
```
