"""
Embedded MCP server integration for Helpdesk Pro.

Initialises the FastAPI-based MCP application in a background thread when the
Flask app starts, sharing configuration and logging facilities.
"""

from __future__ import annotations

import atexit
import fcntl
import logging
import os
import threading
from contextlib import suppress
from typing import Any, Mapping, Optional, TextIO

import uvicorn
from flask import Flask

from .config import configure as configure_settings, get_settings
from .server import app as asgi_app

_thread: Optional[threading.Thread] = None
_server: Optional[uvicorn.Server] = None
_start_lock = threading.Lock()
_atexit_registered = False
_lock_handle: Optional[TextIO] = None
_lock_file_path: Optional[str] = None


def _should_start_in_process(flask_app: Flask) -> bool:
    """Return True if the current process should host the embedded MCP server."""

    global _lock_handle, _lock_file_path

    lock_path = flask_app.config.get("MCP_LOCK_FILE") or os.getenv("MCP_LOCK_FILE") or "/tmp/helpdesk_pro_mcp.lock"
    _lock_file_path = lock_path

    if _lock_handle is not None:
        return True

    try:
        fh = open(lock_path, "a+")
    except OSError:
        flask_app.logger.warning("Unable to open MCP lock file %s; starting MCP anyway.", lock_path)
        return True

    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return False

    try:
        fh.seek(0)
        fh.truncate()
        fh.write(str(os.getpid()))
        fh.flush()
        os.fsync(fh.fileno())
    except OSError:
        # If we fail to write the PID, release the lock and allow another worker to try.
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()
        return False

    _lock_handle = fh
    return True


def init_app(flask_app: Flask) -> None:
    """
    Register lifecycle hooks to launch the MCP server alongside the Flask app.

    The server is lazy-started on the first incoming HTTP request to avoid
    interfering with CLI utilities (e.g. Alembic migrations).
    """

    flask_app.config.setdefault("MCP_ENABLED", True)
    flask_app.config.setdefault("MCP_HOST", "127.0.0.1")
    flask_app.config.setdefault("MCP_PORT", 8081)
    flask_app.config.setdefault("MCP_LOG_LEVEL", flask_app.config.get("LOG_LEVEL", "INFO"))
    flask_app.config.setdefault("MCP_ALLOWED_ORIGINS", [])
    flask_app.config.setdefault("MCP_MAX_ROWS", 1000)
    flask_app.config.setdefault("MCP_REQUEST_TIMEOUT_SECONDS", 10)

    if not flask_app.config.get("MCP_ENABLED", True):
        flask_app.logger.info("MCP server integration is disabled via MCP_ENABLED=0.")
        return

    flask_app.extensions.setdefault("mcp_server", {"started": False})

    def _ensure_started() -> None:
        state = flask_app.extensions.get("mcp_server", {})
        if not state.get("started"):
            start_mcp_server(flask_app)
            state["started"] = True
            flask_app.extensions["mcp_server"] = state

    if hasattr(flask_app, "before_serving"):
        flask_app.before_serving(_ensure_started)  # type: ignore[attr-defined]
    else:  # Flask < 2.3 compatibility
        flask_app.before_request(_ensure_started)


def start_mcp_server(flask_app: Flask) -> None:
    """Start the MCP server once for the given Flask app instance."""

    global _thread, _server, _atexit_registered

    with _start_lock:
        if _thread and _thread.is_alive():
            return

        if not _should_start_in_process(flask_app):
            flask_app.logger.info(
                "Skipping MCP server startup in worker %s", os.getenv("GUNICORN_WORKER_ID")
            )
            return

        overrides = _collect_overrides(flask_app)
        if not overrides.get("database_url"):
            flask_app.logger.warning("Skipping MCP server startup: database URL is not configured.")
            return

        settings = configure_settings(overrides)
        _configure_logging(flask_app)

        config = uvicorn.Config(
            asgi_app,
            host=settings.app_host,
            port=settings.app_port,
            log_config=None,
            log_level=flask_app.config.get("MCP_LOG_LEVEL", "INFO").lower(),
            timeout_keep_alive=flask_app.config.get("MCP_KEEP_ALIVE_SECONDS", 5),
            access_log=flask_app.config.get("MCP_ACCESS_LOG", False),
        )
        server = uvicorn.Server(config)
        _server = server

        def _runner() -> None:
            try:
                flask_app.logger.info(
                    "Starting MCP server on %s:%s (env=%s)",
                    settings.app_host,
                    settings.app_port,
                    settings.environment,
                )
                server.run()
            except Exception:  # pragma: no cover - defensive guard
                flask_app.logger.exception("MCP server crashed unexpectedly.")
            finally:
                flask_app.logger.info("MCP server thread exited.")

        thread = threading.Thread(target=_runner, name="mcp-server", daemon=True)
        thread.start()
        _thread = thread

        if not _atexit_registered:
            atexit.register(stop_mcp_server)
            _atexit_registered = True

        state = flask_app.extensions.setdefault("mcp_server", {})
        state["thread"] = thread
        state["server"] = server
        state["started"] = True


def stop_mcp_server(flask_app: Optional[Flask] = None) -> None:
    """Signal the MCP server to shut down and wait briefly for completion."""

    global _thread, _server, _lock_handle, _lock_file_path

    if _server:
        _server.should_exit = True
        _server.force_exit = True
    if _thread and _thread.is_alive():
        with suppress(TimeoutError):
            _thread.join(timeout=5)
    _thread = None
    _server = None
    if _lock_handle is not None:
        with suppress(OSError):
            fcntl.flock(_lock_handle.fileno(), fcntl.LOCK_UN)
        with suppress(OSError):
            _lock_handle.close()
        _lock_handle = None
    if _lock_file_path:
        with suppress(OSError):
            os.remove(_lock_file_path)
        _lock_file_path = None
    if flask_app is not None:
        state = flask_app.extensions.setdefault("mcp_server", {})
        state["started"] = False


def _collect_overrides(app: Flask) -> Mapping[str, Any]:
    """Prepare configuration overrides based on the Flask app config."""

    db_url = app.config.get("MCP_DATABASE_URL") or _as_async_url(app.config.get("SQLALCHEMY_DATABASE_URI"))
    allowed_origins = app.config.get("MCP_ALLOWED_ORIGINS") or []
    if isinstance(allowed_origins, str):
        allowed_origins = [item.strip() for item in allowed_origins.split(",") if item.strip()]

    base_url = app.config.get("BASE_URL") or app.config.get("MCP_BASE_URL")

    return {
        "database_url": db_url,
        "app_host": app.config.get("MCP_HOST"),
        "app_port": app.config.get("MCP_PORT"),
        "max_rows": app.config.get("MCP_MAX_ROWS"),
        "request_timeout_seconds": app.config.get("MCP_REQUEST_TIMEOUT_SECONDS"),
        "allowed_origins": allowed_origins,
        "base_url": base_url,
        "environment": app.config.get("ENV", "production"),
    }


def _configure_logging(app: Flask) -> None:
    """Share the Flask logging handlers with the embedded MCP stack."""

    level = app.config.get("MCP_LOG_LEVEL", app.logger.level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "helpdesk_pro.mcp"):
        logger = logging.getLogger(name)
        logger.handlers = []
        for handler in app.logger.handlers:
            logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = False


def _as_async_url(url: Optional[str]) -> Optional[str]:
    """Convert a synchronous SQLAlchemy URL to asyncpg if necessary."""

    if not url:
        return None
    if "+asyncpg" in url:
        return url
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("+psycopg2", "+asyncpg", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def refresh_mcp_settings(flask_app: Flask) -> None:
    """
    Apply the latest Flask configuration to the MCP settings cache.

    Useful after environment reloads so helpers like BASE_URL take effect without
    requiring a full server restart.
    """

    if not flask_app.config.get("MCP_ENABLED", True):
        return
    overrides = _collect_overrides(flask_app)
    if not overrides.get("database_url"):
        return
    configure_settings(overrides)
