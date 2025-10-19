# -*- coding: utf-8 -*-
"""
app/models/ticket.py — Ticketing system models for Helpdesk Pro
Final production version with created_by / assigned_to relationships.
"""

import pytz
from datetime import datetime
from app import db


class Ticket(db.Model):
    __tablename__ = "ticket"

    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False)
    priority = db.Column(db.String(50))
    status = db.Column(db.String(50), default="Open")
    department = db.Column(db.String(100))

    # ───────────── Foreign Keys ───────────── #
    created_by = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False)
    assigned_to = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=True)

    # ───────────── Relationships ───────────── #
   # Correct foreign keys
    created_by = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False)
    assigned_to = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=True)

    # Proper relationships
    creator = db.relationship("User", foreign_keys=[
                              created_by], backref="created_tickets")
    assignee = db.relationship("User", foreign_keys=[
                               assigned_to], backref="assigned_tickets")

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    closed_at = db.Column(db.DateTime)

    # ───────────── Helper Properties ───────────── #
    @property
    def created_at_local(self):
        """Convert UTC → Europe/Athens safely."""
        if not self.created_at:
            return None
        tz = pytz.timezone("Europe/Athens")
        return self.created_at.replace(tzinfo=pytz.utc).astimezone(tz)

    @property
    def closed_at_local(self):
        """Convert UTC → Europe/Athens safely."""
        if not self.closed_at:
            return None
        tz = pytz.timezone("Europe/Athens")
        return self.closed_at.replace(tzinfo=pytz.utc).astimezone(tz)

    # ───────────── Reverse Relationships ───────────── #
    comments = db.relationship(
        "TicketComment",
        backref="ticket",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    attachments = db.relationship(
        "Attachment",
        backref="ticket",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    logs = db.relationship(
        "AuditLog",
        backref="ticket",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self):
        return f"<Ticket {self.id}: {self.subject}>"


class TicketComment(db.Model):
    __tablename__ = "ticket_comment"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(
        db.Integer, db.ForeignKey("ticket.id", ondelete="CASCADE"), nullable=False
    )
    user = db.Column(db.String(100))
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def created_at_local(self):
        """Convert UTC → Europe/Athens safely."""
        if not self.created_at:
            return None
        tz = pytz.timezone("Europe/Athens")
        return self.created_at.replace(tzinfo=pytz.utc).astimezone(tz)

    def __repr__(self):
        return f"<Comment #{self.id} by {self.user}>"


class Attachment(db.Model):
    __tablename__ = "attachment"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(
        db.Integer, db.ForeignKey("ticket.id", ondelete="CASCADE"), nullable=False
    )
    filename = db.Column(db.String(255))
    filepath = db.Column(db.String(255))
    uploaded_by = db.Column(db.String(100))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def uploaded_at_local(self):
        """Convert UTC → Europe/Athens safely."""
        if not self.uploaded_at:
            return None
        tz = pytz.timezone("Europe/Athens")
        return self.uploaded_at.replace(tzinfo=pytz.utc).astimezone(tz)

    def __repr__(self):
        return f"<Attachment {self.filename}>"


class AuditLog(db.Model):
    __tablename__ = "audit_log"

    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(100))
    username = db.Column(db.String(100))
    ticket_id = db.Column(
        db.Integer, db.ForeignKey("ticket.id", ondelete="CASCADE"), nullable=True
    )
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def timestamp_local(self):
        """Convert UTC → Europe/Athens safely."""
        if not self.timestamp:
            return None
        tz = pytz.timezone("Europe/Athens")
        return self.timestamp.replace(tzinfo=pytz.utc).astimezone(tz)

    def __repr__(self):
        return f"<AuditLog {self.action} by {self.username}>"
