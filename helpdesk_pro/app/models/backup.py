# -*- coding: utf-8 -*-
"""
Data models for the Backup Monitor module.
Handles removable storage media (tape cartridges and external disks),
storage locations, custody history, and auditing of status/location/retention
changes.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, Sequence

from sqlalchemy import and_
from sqlalchemy.orm import foreign

from app import db


class TapeCartridge(db.Model):
    __tablename__ = "backup_tape_cartridge"

    id = db.Column(db.Integer, primary_key=True)
    barcode = db.Column(db.String(64), nullable=False, unique=True)
    lto_generation = db.Column(db.String(16), nullable=True)
    medium_type = db.Column(db.String(20), nullable=False, default="tape")
    serial_number = db.Column(db.String(120), nullable=True)
    manufacturer = db.Column(db.String(120), nullable=True)
    model_name = db.Column(db.String(120), nullable=True)
    nominal_capacity_tb = db.Column(db.Numeric(10, 2), nullable=True)
    usable_capacity_tb = db.Column(db.Numeric(10, 2), nullable=True)
    status = db.Column(db.String(32), nullable=False, default="empty")
    usage_tags = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    last_inventory_at = db.Column(db.DateTime, nullable=True)
    retention_days = db.Column(db.Integer, nullable=True)
    retention_start_at = db.Column(db.DateTime, nullable=True)
    retention_until = db.Column(db.DateTime, nullable=True)

    current_location_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "backup_tape_location.id",
            name="fk_backup_tape_current_location",
            use_alter=True,
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    current_location = db.relationship(
        "TapeLocation",
        foreign_keys=[current_location_id],
        post_update=True,
    )
    locations = db.relationship(
        "TapeLocation",
        back_populates="tape",
        order_by="TapeLocation.created_at.desc()",
        foreign_keys="TapeLocation.tape_id",
        cascade="all, delete-orphan",
    )
    custody_events = db.relationship(
        "TapeCustodyEvent",
        back_populates="tape",
        order_by="TapeCustodyEvent.event_time.desc()",
        foreign_keys="TapeCustodyEvent.tape_id",
        cascade="all, delete-orphan",
    )
    def usage_tag_list(self) -> list[str]:
        if not self.usage_tags:
            return []
        return [tag.strip() for tag in self.usage_tags.split(",") if tag.strip()]

    def set_usage_tags(self, tags: Sequence[str]) -> None:
        cleaned = [t.strip() for t in tags if t and t.strip()]
        self.usage_tags = ", ".join(sorted(set(cleaned)))

    def sync_retention(self) -> None:
        if not self.retention_days:
            self.retention_until = None
            return
        start = self.retention_start_at or datetime.utcnow()
        try:
            self.retention_until = start + timedelta(days=self.retention_days)
        except OverflowError:  # pragma: no cover
            self.retention_until = None

    def retention_remaining_days(self) -> Optional[int]:
        if not self.retention_until:
            return None
        today = datetime.utcnow().date()
        remaining = (self.retention_until.date() - today).days
        return remaining

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<TapeCartridge {self.barcode} type={self.medium_type} status={self.status}>"


class TapeLocation(db.Model):
    __tablename__ = "backup_tape_location"

    id = db.Column(db.Integer, primary_key=True)
    tape_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "backup_tape_cartridge.id",
            name="fk_backup_location_tape",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    location_type = db.Column(db.String(20), nullable=False)
    site_name = db.Column(db.String(120), nullable=True)
    shelf_code = db.Column(db.String(80), nullable=True)
    locker_code = db.Column(db.String(80), nullable=True)
    provider_name = db.Column(db.String(120), nullable=True)
    provider_contact = db.Column(db.String(120), nullable=True)
    custody_holder = db.Column(db.String(120), nullable=True)
    custody_reference = db.Column(db.String(120), nullable=True)
    check_in_at = db.Column(db.DateTime, nullable=True)
    check_out_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    is_current = db.Column(db.Boolean, default=True, nullable=False)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    tape = db.relationship(
        "TapeCartridge",
        back_populates="locations",
        foreign_keys=[tape_id],
    )
    created_by = db.relationship("User")
    audit_entries = db.relationship(
        "BackupAuditLog",
        primaryjoin=lambda: and_(
            BackupAuditLog.entity_type == "location",
            foreign(BackupAuditLog.entity_id) == TapeLocation.id,
        ),
        viewonly=True,
        order_by="BackupAuditLog.created_at.desc()",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TapeLocation {self.location_type} tape={self.tape_id}>"


class TapeCustodyEvent(db.Model):
    __tablename__ = "backup_tape_custody"

    id = db.Column(db.Integer, primary_key=True)
    tape_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "backup_tape_cartridge.id",
            name="fk_backup_custody_tape",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    event_type = db.Column(db.String(32), nullable=False, default="transfer")
    event_time = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    handed_over_by = db.Column(db.String(120), nullable=True)
    handed_over_signature = db.Column(db.String(120), nullable=True)
    received_by = db.Column(db.String(120), nullable=True)
    received_signature = db.Column(db.String(120), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)

    tape = db.relationship(
        "TapeCartridge",
        back_populates="custody_events",
        foreign_keys=[tape_id],
    )
    created_by = db.relationship("User")
    audit_entries = db.relationship(
        "BackupAuditLog",
        primaryjoin=lambda: and_(
            BackupAuditLog.entity_type == "custody",
            foreign(BackupAuditLog.entity_id) == TapeCustodyEvent.id,
        ),
        viewonly=True,
        order_by="BackupAuditLog.created_at.desc()",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TapeCustodyEvent tape={self.tape_id} type={self.event_type}>"


class BackupAuditLog(db.Model):
    __tablename__ = "backup_audit_log"

    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(32), nullable=False)
    entity_id = db.Column(db.Integer, nullable=False)
    field_name = db.Column(db.String(64), nullable=True)
    old_value = db.Column(db.Text, nullable=True)
    new_value = db.Column(db.Text, nullable=True)
    reason = db.Column(db.Text, nullable=True)
    changed_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    changed_by_username = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    changed_by = db.relationship("User")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<BackupAuditLog {self.entity_type}#{self.entity_id} {self.field_name}>"
