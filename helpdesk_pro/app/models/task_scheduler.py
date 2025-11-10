# -*- coding: utf-8 -*-
"""
Data models for the Task Scheduler module.
Tracks tasks, user slots, share tokens, and audit events.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app import db


class TaskSchedulerTask(db.Model):
    __tablename__ = "task_scheduler_task"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, nullable=True)
    estimated_duration_label = db.Column(db.String(64), nullable=False, default="1-2 hours")
    estimated_duration_minutes_min = db.Column(db.Integer, nullable=False, default=60)
    estimated_duration_minutes_max = db.Column(db.Integer, nullable=False, default=120)
    status = db.Column(db.String(16), nullable=False, default="Shared")
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    updated_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    created_by = db.relationship("User", foreign_keys=[created_by_user_id], lazy="joined")
    updated_by = db.relationship("User", foreign_keys=[updated_by_user_id], lazy="joined")
    slots = db.relationship(
        "TaskSchedulerSlot",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskSchedulerSlot.start_at.asc()",
    )
    share_tokens = db.relationship(
        "TaskSchedulerShareToken",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskSchedulerShareToken.created_at.desc()",
    )
    audits = db.relationship(
        "TaskSchedulerAuditLog",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskSchedulerAuditLog.created_at.desc()",
    )

    def as_badge_variant(self) -> str:
        if self.status == "Closed":
            return "danger"
        return "success"

    def duration_window_hours(self) -> str:
        return self.estimated_duration_label or "—"


class TaskSchedulerSlot(db.Model):
    __tablename__ = "task_scheduler_slot"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(
        db.Integer,
        db.ForeignKey("task_scheduler_task.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    display_name = db.Column(db.String(160), nullable=False)
    start_at = db.Column(db.DateTime, nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False, default=60)
    comment = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    created_via = db.Column(db.String(32), nullable=False, default="admin")

    task = db.relationship("TaskSchedulerTask", back_populates="slots")
    user = db.relationship("User", foreign_keys=[user_id], lazy="joined")
    created_by = db.relationship("User", foreign_keys=[created_by_user_id], lazy="joined")

    @property
    def end_at(self):
        if not self.start_at or not self.duration_minutes:
            return None
        return self.start_at + timedelta(minutes=self.duration_minutes)


class TaskSchedulerShareToken(db.Model):
    __tablename__ = "task_scheduler_share_token"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(
        db.Integer,
        db.ForeignKey("task_scheduler_task.id", ondelete="CASCADE"),
        nullable=False,
    )
    token = db.Column(db.String(64), nullable=False, unique=True, index=True)
    visibility = db.Column(db.String(16), nullable=False, default="public")  # public|restricted
    expires_at = db.Column(db.DateTime, nullable=True)
    revoked_at = db.Column(db.DateTime, nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    task = db.relationship("TaskSchedulerTask", back_populates="share_tokens")
    created_by = db.relationship("User")

    def is_active(self) -> bool:
        if self.revoked_at:
            return False
        if self.expires_at and self.expires_at < datetime.utcnow():
            return False
        return True

    def require_login(self) -> bool:
        return self.visibility == "restricted"


class TaskSchedulerAuditLog(db.Model):
    __tablename__ = "task_scheduler_audit_log"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(
        db.Integer,
        db.ForeignKey("task_scheduler_task.id", ondelete="CASCADE"),
        nullable=False,
    )
    action = db.Column(db.String(64), nullable=False)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    payload = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    task = db.relationship("TaskSchedulerTask", back_populates="audits")
    actor = db.relationship("User")

    @staticmethod
    def record(task_id: int, action: str, actor_id=None, payload=None):
        entry = TaskSchedulerAuditLog(
            task_id=task_id,
            action=action,
            actor_user_id=actor_id,
            payload=payload or {},
        )
        db.session.add(entry)
        return entry
