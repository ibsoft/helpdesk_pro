# -*- coding: utf-8 -*-
"""
Email-to-ticket ingestion configuration model.
Stores IMAP/POP3 connection details and processing preferences.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import inspect

from app import db


class EmailIngestConfig(db.Model):
    __tablename__ = "email_ingest_config"

    id = db.Column(db.Integer, primary_key=True)
    is_enabled = db.Column(db.Boolean, default=False, nullable=False)

    protocol = db.Column(db.String(8), default="imap", nullable=False)  # imap | pop3
    host = db.Column(db.String(255))
    port = db.Column(db.Integer)
    use_ssl = db.Column(db.Boolean, default=True, nullable=False)
    mailbox = db.Column(db.String(120), default="INBOX")

    username = db.Column(db.String(255))
    password = db.Column(db.String(255))

    poll_interval_seconds = db.Column(db.Integer, default=300, nullable=False)

    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    assign_to_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    default_priority = db.Column(db.String(50))
    default_department = db.Column(db.String(120))

    last_run_at = db.Column(db.DateTime)
    last_error = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    created_by_user = db.relationship("User", foreign_keys=[created_by_user_id])
    assign_to_user = db.relationship("User", foreign_keys=[assign_to_user_id])

    @classmethod
    def load(cls) -> "EmailIngestConfig":
        engine = db.get_engine()
        if not inspect(engine).has_table(cls.__tablename__):
            # Table not created yet (e.g., during migrations); return an in-memory config.
            instance = cls()
            instance._table_missing = True
            return instance

        instance: Optional["EmailIngestConfig"] = cls.query.order_by(cls.id.asc()).first()
        if not instance:
            instance = cls()
            db.session.add(instance)
            db.session.commit()
        # Flag used by callers (e.g., the manage blueprint) to detect whether the underlying table exists.
        instance._table_missing = False
        if instance.protocol not in {"imap", "pop3"}:
            instance.protocol = "imap"
            db.session.add(instance)
            db.session.commit()
        if not instance.mailbox:
            instance.mailbox = "INBOX"
            db.session.add(instance)
            db.session.commit()
        if not instance.poll_interval_seconds or instance.poll_interval_seconds < 30:
            instance.poll_interval_seconds = 300
            db.session.add(instance)
            db.session.commit()
        return instance

    def update_from_form(self, form_data) -> None:
        self.is_enabled = bool(form_data.get("is_enabled"))
        protocol = (form_data.get("protocol") or "imap").lower()
        self.protocol = protocol if protocol in {"imap", "pop3"} else "imap"
        self.host = (form_data.get("host") or "").strip()
        try:
            port = int(form_data.get("port") or 0)
        except (TypeError, ValueError):
            port = 0
        self.port = port or None
        self.use_ssl = bool(form_data.get("use_ssl"))
        mailbox = (form_data.get("mailbox") or "").strip()
        self.mailbox = mailbox or "INBOX"
        self.username = (form_data.get("username") or "").strip()
        password_field = form_data.get("password")
        if password_field is not None and password_field != "***":
            self.password = password_field.strip() or None
        try:
            interval = int(form_data.get("poll_interval_seconds") or 0)
        except (TypeError, ValueError):
            interval = 300
        self.poll_interval_seconds = max(interval, 30)
        self.default_priority = (form_data.get("default_priority") or "").strip() or None
        self.default_department = (form_data.get("default_department") or "").strip() or None
        created_by = form_data.get("created_by_user_id")
        assign_to = form_data.get("assign_to_user_id")
        self.created_by_user_id = int(created_by) if created_by and str(created_by).isdigit() else None
        self.assign_to_user_id = int(assign_to) if assign_to and str(assign_to).isdigit() else None
