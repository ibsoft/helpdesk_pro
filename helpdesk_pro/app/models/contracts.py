# -*- coding: utf-8 -*-
"""
Contract management models.
Provides contract registry support with lifecycle tracking for Helpdesk Pro.
"""

from datetime import datetime
from decimal import Decimal

from app import db


class Contract(db.Model):
    __tablename__ = "contract"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    contract_type = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(120))
    vendor = db.Column(db.String(150))
    contract_number = db.Column(db.String(120), unique=True)
    po_number = db.Column(db.String(120))
    value = db.Column(db.Numeric(12, 2))
    currency = db.Column(db.String(8))
    auto_renew = db.Column(db.Boolean, default=False, nullable=False)
    notice_period_days = db.Column(db.Integer)
    coverage_scope = db.Column(db.String(255))
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    renewal_date = db.Column(db.Date)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    support_email = db.Column(db.String(150))
    support_phone = db.Column(db.String(80))
    support_url = db.Column(db.String(255))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = db.relationship("User", foreign_keys=[owner_id], backref="contracts")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name or "",
            "contract_type": self.contract_type or "",
            "status": self.status or "",
            "vendor": self.vendor or "",
            "contract_number": self.contract_number or "",
            "po_number": self.po_number or "",
            "value": str(self.value) if isinstance(self.value, Decimal) else (f"{self.value:.2f}" if self.value is not None else ""),
            "currency": self.currency or "",
            "auto_renew": bool(self.auto_renew),
            "notice_period_days": self.notice_period_days or "",
            "coverage_scope": self.coverage_scope or "",
            "start_date": self.start_date.isoformat() if self.start_date else "",
            "end_date": self.end_date.isoformat() if self.end_date else "",
            "renewal_date": self.renewal_date.isoformat() if self.renewal_date else "",
            "owner_id": self.owner_id,
            "owner_name": self.owner.username if self.owner else "",
            "support_email": self.support_email or "",
            "support_phone": self.support_phone or "",
            "support_url": self.support_url or "",
            "notes": self.notes or "",
        }

    def __repr__(self):
        return f"<Contract {self.name} ({self.contract_type})>"
