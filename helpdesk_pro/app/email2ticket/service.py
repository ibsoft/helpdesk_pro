# -*- coding: utf-8 -*-
"""
Background worker for ingesting emails into Helpdesk Pro tickets.
Supports IMAP and POP3 mailboxes with simple polling.
"""

from __future__ import annotations

import os
import re
import ssl
import threading
from datetime import datetime
from email import message_from_bytes
from email.header import decode_header
from email.utils import parseaddr
from html import unescape
from typing import Optional, Tuple, List

import imaplib
import poplib

from app.utils.files import secure_filename

from app import db
from app.models import EmailIngestConfig, Ticket, Attachment, AuditLog, User


_worker_lock = threading.Lock()
_worker: Optional["EmailToTicketWorker"] = None


def init_app(app) -> None:
    """Hook to start the background worker when the Flask app boots."""
    if not app.config.get("EMAIL2TICKET_AUTOSTART", True):
        return
    if app.config.get("TESTING"):
        return
    # Skip when running flask CLI management commands (e.g. migrations).
    import sys

    if len(sys.argv) > 1 and sys.argv[0].endswith("flask") and sys.argv[1] in {"db", "shell", "routes"}:
        return
    # Avoid double-start in debug reloader
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return
    ensure_worker_running(app)


def ensure_worker_running(app, reload_cfg: bool = False) -> None:
    """Ensure the polling worker is running (or stopped if disabled)."""
    global _worker
    with _worker_lock:
        if _worker is None:
            _worker = EmailToTicketWorker(app)
            _worker.start()
        else:
            if reload_cfg:
                _worker.signal_reload()


def run_once(app) -> int:
    """Process the mailbox immediately (used by admin UI)."""
    with app.app_context():
        cfg = EmailIngestConfig.load()
        if not cfg.is_enabled:
            raise RuntimeError("Email ingestion is disabled.")
        processed = EmailToTicketWorker.process_mailbox(cfg, app)
        return processed


class EmailToTicketWorker:
    """Background thread polling a mailbox at the configured interval."""

    def __init__(self, app):
        self.app = app
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._reload = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="EmailToTicketWorker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def signal_reload(self) -> None:
        self._reload.set()

    def _run(self) -> None:
        with self.app.app_context():
            while not self._stop.is_set():
                cfg = EmailIngestConfig.load()
                interval = max(cfg.poll_interval_seconds or 300, 30)

                if not cfg.is_enabled:
                    self._wait(interval)
                    continue

                try:
                    processed = self.process_mailbox(cfg, self.app)
                    cfg.last_run_at = datetime.utcnow()
                    cfg.last_error = None
                    db.session.add(cfg)
                    db.session.commit()
                    if processed:
                        self.app.logger.info("Email2Ticket ingested %s email(s).", processed)
                except Exception as exc:  # pragma: no cover
                    db.session.rollback()
                    cfg.last_run_at = datetime.utcnow()
                    cfg.last_error = str(exc)
                    db.session.add(cfg)
                    db.session.commit()
                    self.app.logger.exception("Email2Ticket worker failed: %s", exc)

                self._wait(interval)

    def _wait(self, seconds: int) -> None:
        waited = 0
        while not self._stop.is_set() and waited < seconds:
            if self._reload.is_set():
                self._reload.clear()
                break
            remaining = min(1, seconds - waited)
            self._stop.wait(remaining)
            waited += remaining

    @staticmethod
    def process_mailbox(cfg: EmailIngestConfig, app) -> int:
        if not cfg.host or not cfg.username or not cfg.password:
            raise RuntimeError("Mailbox connection is not fully configured.")

        if cfg.protocol == "pop3":
            return EmailToTicketWorker._process_pop3(cfg, app)
        return EmailToTicketWorker._process_imap(cfg, app)

    @staticmethod
    def _process_imap(cfg: EmailIngestConfig, app) -> int:
        ssl_context = ssl.create_default_context()
        if cfg.use_ssl:
            imap = imaplib.IMAP4_SSL(cfg.host, cfg.port or 993, ssl_context=ssl_context)
        else:
            imap = imaplib.IMAP4(cfg.host, cfg.port or 143)
        try:
            imap.login(cfg.username, cfg.password)
            inbox = cfg.mailbox or "INBOX"
            imap.select(inbox, readonly=False)
            typ, data = imap.search(None, "UNSEEN")
            if typ != "OK":
                raise RuntimeError("Failed to search mailbox: %s" % typ)
            message_ids = data[0].split()
            processed = 0
            for msg_id in message_ids:
                typ, msg_data = imap.fetch(msg_id, "(RFC822)")
                if typ != "OK":
                    continue
                try:
                    result = EmailToTicketWorker._store_message(msg_data[0][1], cfg, app)
                    if result is True:
                        imap.store(msg_id, "+FLAGS", r"(\Deleted)")
                        processed += 1
                    elif result is False and cfg.subject_filter_delete_non_matching:
                        imap.store(msg_id, "+FLAGS", r"(\Deleted)")
                    else:
                        imap.store(msg_id, "+FLAGS", r"(\Seen)")
                except Exception as exc:  # pragma: no cover
                    app.logger.exception("Failed to ingest email via IMAP: %s", exc)
            if processed:
                imap.expunge()
            return processed
        finally:
            try:
                imap.logout()
            except Exception:  # pragma: no cover
                pass

    @staticmethod
    def _process_pop3(cfg: EmailIngestConfig, app) -> int:
        if cfg.use_ssl:
            pop = poplib.POP3_SSL(cfg.host, cfg.port or 995)
        else:
            pop = poplib.POP3(cfg.host, cfg.port or 110)
        try:
            pop.user(cfg.username)
            pop.pass_(cfg.password)
            processed = 0
            num_messages = len(pop.list()[1])
            for index in range(num_messages):
                response, lines, _ = pop.retr(index + 1)
                if not response.startswith(b"+OK"):
                    continue
                message_bytes = b"\r\n".join(lines)
                try:
                    result = EmailToTicketWorker._store_message(message_bytes, cfg, app)
                    if result is not None:
                        if result or cfg.subject_filter_delete_non_matching:
                            pop.dele(index + 1)
                        if result:
                            processed += 1
                except Exception as exc:  # pragma: no cover
                    app.logger.exception("Failed to ingest email via POP3: %s", exc)
            pop.quit()
            return processed
        finally:
            try:
                pop.close()
            except Exception:  # pragma: no cover
                pass

    @staticmethod
    def _store_message(message_bytes: bytes, cfg: EmailIngestConfig, app) -> Optional[bool]:
        email_message = message_from_bytes(message_bytes)
        subject = _decode_header(email_message.get("Subject")) or app.config.get(
            "EMAIL2TICKET_DEFAULT_SUBJECT", "Email request"
        )
        from_header = _decode_header(email_message.get("From") or "")
        sender_name, sender_email = parseaddr(from_header)
        body, attachments = _extract_content(email_message, app)

        if cfg.subject_filter_enabled:
            patterns = cfg.get_subject_patterns()
            if patterns and not _subject_matches_patterns(subject, patterns):
                app.logger.debug("Skipping email with subject '%s' (no pattern matched).", subject)
                return False

        created_by_id = cfg.created_by_user_id or _find_fallback_user_id()
        if not created_by_id:
            raise RuntimeError("No default user available to own the ticket.")

        ticket = Ticket(
            subject=subject[:255] if subject else "Email request",
            description=_build_description(body, sender_name, sender_email),
            priority=cfg.default_priority,
            status="Open",
            department=cfg.default_department,
            created_by=created_by_id,
            assigned_to=cfg.assign_to_user_id,
        )
        db.session.add(ticket)
        db.session.flush()

        for attachment_path, original_name in attachments:
            db.session.add(
                Attachment(
                    ticket_id=ticket.id,
                    filename=original_name[:255],
                    filepath=attachment_path,
                    uploaded_by=sender_email or "email2ticket",
                )
            )

        db.session.add(
            AuditLog(
                action="Email ingest",
                username=sender_email or "email2ticket",
                ticket_id=ticket.id,
            )
        )
        db.session.commit()
        return True


def _subject_matches_patterns(subject: Optional[str], patterns: List[str]) -> bool:
    """Return True when the subject matches at least one configured pattern."""
    subject_text = subject or ""
    subject_lower = subject_text.lower()
    for raw_pattern in patterns:
        pattern = (raw_pattern or "").strip()
        if not pattern:
            continue
        lowered = pattern.lower()
        if lowered.startswith("regex:"):
            expr = pattern.split(":", 1)[1].strip()
            if not expr:
                continue
            try:
                if re.search(expr, subject_text, re.IGNORECASE):
                    return True
            except re.error:
                continue
            continue
        if "*" in pattern:
            wildcard_regex = re.escape(pattern).replace(r"\*", ".*")
            if re.search(wildcard_regex, subject_text, re.IGNORECASE):
                return True
            continue
        if pattern.lower() in subject_lower:
            return True
    return False


def _decode_header(value: Optional[str]) -> str:
    if not value:
        return ""
    decoded_parts = []
    for part, encoding in decode_header(value):
        if isinstance(part, bytes):
            try:
                decoded_parts.append(part.decode(encoding or "utf-8", errors="replace"))
            except Exception:
                decoded_parts.append(part.decode("utf-8", errors="replace"))
        else:
            decoded_parts.append(part)
    return "".join(decoded_parts).strip()


def _extract_content(email_message, app) -> Tuple[str, List[Tuple[str, str]]]:
    text_parts: List[str] = []
    html_parts: List[str] = []
    attachments: List[Tuple[str, str]] = []
    storage_dir = app.config.get(
        "EMAIL2TICKET_STORAGE", os.path.join(app.instance_path, "email2ticket")
    )
    os.makedirs(storage_dir, exist_ok=True)

    for part in email_message.walk():
        content_disposition = part.get("Content-Disposition", "")
        if part.get_content_maintype() == "multipart":
            continue
        payload = part.get_payload(decode=True) or b""
        charset = part.get_content_charset() or "utf-8"

        if "attachment" in (content_disposition or "").lower():
            filename = part.get_filename()
            decoded_name = _decode_header(filename) if filename else "attachment.bin"
            safe_name = secure_filename(decoded_name, allow_unicode=True) or "attachment.bin"
            stamp = int(datetime.utcnow().timestamp() * 1000)
            full_path = os.path.join(storage_dir, f"{stamp}_{safe_name}")
            with open(full_path, "wb") as handle:
                handle.write(payload)
            attachments.append((full_path, decoded_name))
            continue

        try:
            text = payload.decode(charset, errors="replace")
        except Exception:
            text = payload.decode("utf-8", errors="replace")

        content_type = part.get_content_type()
        if content_type == "text/html":
            html_parts.append(text)
        else:
            text_parts.append(text)

    body_text = "\n".join(text_parts).strip()
    if not body_text and html_parts:
        body_text = _html_to_text("\n\n".join(html_parts))
    body_text = body_text or "(no content)"
    return body_text, attachments


def _html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", html)
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    html = re.sub(r"(?i)</p>", "\n\n", html)
    html = re.sub(r"(?i)<li>", "\n• ", html)
    text = re.sub(r"<[^>]+>", "", html)
    text = unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _build_description(body: str, sender_name: str, sender_email: str) -> str:
    header_lines = []
    if sender_name or sender_email:
        sender_line = sender_email or ""
        if sender_name and sender_name not in sender_line:
            sender_line = f"{sender_name} <{sender_line}>" if sender_line else sender_name
        header_lines.append(f"Email from: {sender_line}")
    header_lines.append("")
    header_lines.append(body)
    return "\n".join(header_lines).strip()


def _find_fallback_user_id() -> Optional[int]:
    user = (
        User.query.filter(User.role == "admin", User.active.is_(True))
        .order_by(User.id.asc())
        .first()
    )
    if user:
        return user.id
    user = User.query.order_by(User.id.asc()).first()
    return user.id if user else None
