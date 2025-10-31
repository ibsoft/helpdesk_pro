"""
Database utilities for the MCP server.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Sequence

from sqlalchemy import text
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    settings = get_settings()
    if (
        _engine
        and _session_factory
        and str(_engine.url) == settings.database_url
        and _engine.echo == (settings.environment == "development")
    ):
        return _session_factory

    _engine = create_async_engine(
        settings.database_url,
        echo=settings.environment == "development",
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
    )
    _session_factory = async_sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession with automatic cleanup."""

    SessionLocal = _get_session_factory()
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def fetch_all(query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Run a read-only query and return rows as dictionaries."""

    params = params or {}
    async with get_session() as session:
        result: Result = await session.execute(text(query), params)
        rows = result.mappings().all()
        return [dict(row) for row in rows]


async def fetch_one(query: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Return a single row (or None) as a dictionary."""

    params = params or {}
    async with get_session() as session:
        result: Result = await session.execute(text(query), params)
        record = result.mappings().first()
        return dict(record) if record else None


async def fetch_value(query: str, params: dict[str, Any] | None = None) -> Any:
    """Return a single scalar value."""

    params = params or {}
    async with get_session() as session:
        result: Result = await session.execute(text(query), params)
        return result.scalar_one()
