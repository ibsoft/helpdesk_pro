from __future__ import annotations

import threading
from contextlib import contextmanager
from smtplib import SMTPNotSupportedError

from flask import current_app

from app import mail
from app.background import submit_background_task

_AUTH_SWAP_LOCK = threading.Lock()


@contextmanager
def _disable_mail_auth_temporarily(mail_state):
    """Temporarily clear SMTP credentials so Flask-Mail skips LOGIN."""
    original_username = getattr(mail_state, "username", None)
    original_password = getattr(mail_state, "password", None)

    mail_state.username = None
    mail_state.password = None
    try:
        yield
    finally:
        mail_state.username = original_username
        mail_state.password = original_password


def send_mail_with_optional_auth(message) -> None:
    """Send a Message, retrying without SMTP AUTH if the server forbids it."""
    try:
        mail.send(message)
        return
    except SMTPNotSupportedError:
        app = current_app._get_current_object()  # ensure stable reference
        fallback_enabled = app.config.get("MAIL_FALLBACK_TO_NO_AUTH", True)

        if not fallback_enabled:
            raise

        mail_state = app.extensions.get("mail")
        if mail_state is None:
            raise

        if not getattr(mail_state, "username", None):
            # Credentials already absent; nothing else to try.
            raise

        app.logger.warning(
            "SMTP server %s does not advertise AUTH; retrying without credentials.",
            getattr(mail_state, "server", "<unknown>"),
        )

        with _AUTH_SWAP_LOCK:
            with _disable_mail_auth_temporarily(mail_state):
                mail.send(message)


def queue_mail_with_optional_auth(message, description: str | None = None):
    """Schedule mail delivery on the background executor."""
    recipients = getattr(message, "recipients", None) or []
    inferred = ", ".join(recipients)
    desc = description or (f"email to {inferred}" if inferred else "email send")
    submit_background_task(
        send_mail_with_optional_auth,
        message,
        description=desc,
    )
