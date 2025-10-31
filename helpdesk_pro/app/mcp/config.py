"""
Configuration handling for the embedded MCP server.

Retains environment-based defaults while allowing overrides injected from the
Flask application configuration at runtime.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment or app overrides."""

    database_url: str = Field(
        ...,
        validation_alias=AliasChoices("MCP_DATABASE_URL", "SQLALCHEMY_DATABASE_URI"),
        description="Async database URL, e.g. postgresql+asyncpg://user:pass@host/db",
    )
    app_host: str = Field("0.0.0.0", alias="MCP_HOST")
    app_port: int = Field(8081, alias="MCP_PORT")
    max_rows: int = Field(1000, alias="MCP_MAX_ROWS")
    request_timeout_seconds: int = Field(10, alias="MCP_REQUEST_TIMEOUT")
    allowed_origins: list[str] = Field(default_factory=list, alias="MCP_ALLOWED_ORIGINS")
    base_url: Optional[str] = Field(default=None, alias="BASE_URL")
    environment: str = Field("development", alias="MCP_ENV")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


_settings_cache: Optional[Settings] = None
settings: Settings


def configure(overrides: Optional[Mapping[str, Any]] = None) -> Settings:
    """
    Populate the settings cache using optional mapping overrides.

    Values in ``overrides`` take precedence when provided; unset values fall back
    to environment defaults handled by ``BaseSettings``.
    """

    global _settings_cache, settings
    base = Settings()  # type: ignore[arg-type]
    if overrides:
        cleaned = {key: value for key, value in overrides.items() if value is not None}
        _settings_cache = base.model_copy(update=cleaned)
    else:
        _settings_cache = base
    settings = _settings_cache
    return _settings_cache


def get_settings() -> Settings:
    """Return the cached settings, loading from environment if necessary."""

    global _settings_cache, settings
    if _settings_cache is None:
        _settings_cache = configure()
    settings = _settings_cache
    return _settings_cache
settings = get_settings()
