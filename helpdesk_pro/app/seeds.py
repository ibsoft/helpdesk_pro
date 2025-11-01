import os
from time import sleep
from typing import Any

from sqlalchemy import or_
from sqlalchemy.exc import OperationalError

from app import db
from app.models.user import User


def _should_create_admin() -> bool:
    return _env_bool("CREATE_DEFAULT_ADMIN", True)


def _should_sync_existing_admin() -> bool:
    return _env_bool("DEFAULT_ADMIN_SYNC", False)


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env(key: str, default: str | None = None) -> str | None:
    value = os.getenv(key)
    if value is None or not value.strip():
        return default
    return value.strip()


def ensure_default_admin(app: Any) -> None:
    """Create a default admin user if one does not already exist."""
    if not _should_create_admin():
        app.logger.info("Skipping default admin creation (CREATE_DEFAULT_ADMIN disabled).")
        return

    username = _env("DEFAULT_ADMIN_USERNAME", "admin")
    email = _env("DEFAULT_ADMIN_EMAIL", "admin@example.com")
    password = _env("DEFAULT_ADMIN_PASSWORD", "Admin123!")
    full_name = _env("DEFAULT_ADMIN_FULL_NAME", "System Administrator")
    department = _env("DEFAULT_ADMIN_DEPARTMENT", "IT")

    if not password:
        app.logger.warning("DEFAULT_ADMIN_PASSWORD not provided; cannot seed default admin.")
        return

    existing = User.query.filter(or_(User.username == username, User.email == email)).first()
    if existing:
        if not _should_sync_existing_admin():
            app.logger.debug("Default admin seed skipped; matching user already exists.")
            return

        # Sync basic fields and optionally reset the password.
        changed = False

        if existing.username != username:
            app.logger.warning(
                "Existing admin username '%s' differs from DEFAULT_ADMIN_USERNAME '%s'; keeping stored value.",
                existing.username,
                username,
            )
        if existing.email != email:
            existing.email = email
            changed = True
        if full_name and existing.full_name != full_name:
            existing.full_name = full_name
            changed = True
        if department and existing.department != department:
            existing.department = department
            changed = True
        if not existing.active:
            existing.active = True
            changed = True

        existing.set_password(password)
        changed = True

        if changed:
            db.session.commit()
            app.logger.info("Default admin updated in place (username=%s).", existing.username)
        else:
            app.logger.debug("Default admin already up to date (username=%s).", existing.username)
        return

    admin = User(
        username=username,
        email=email,
        full_name=full_name,
        role="admin",
        department=department,
        active=True,
    )
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()
    app.logger.info("Default admin created (username=%s).", username)


def ensure_default_admin_with_retry(app: Any) -> None:
    """Retry wrapper so container startup can handle transient DB availability."""
    attempts = int(_env("DEFAULT_ADMIN_RETRY_ATTEMPTS", "5") or "5")
    delay = float(_env("DEFAULT_ADMIN_RETRY_DELAY", "2") or "2")

    for attempt in range(1, attempts + 1):
        try:
            ensure_default_admin(app)
            return
        except OperationalError as exc:
            if attempt == attempts:
                app.logger.error(
                    "Unable to seed default admin after %d attempts: %s", attempt, exc
                )
                raise
            app.logger.warning(
                "Database not ready (attempt %d/%d): %s; retrying in %.1f sec",
                attempt,
                attempts,
                exc,
                delay,
            )
            sleep(delay)
