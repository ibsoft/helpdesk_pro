# -*- coding: utf-8 -*-
"""
Contract management models.
Provides contract registry support with lifecycle tracking for Helpdesk Pro.
"""

from datetime import datetime, timedelta
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
    history = db.relationship(
        "ContractUpdateHistory",
        back_populates="contract",
        cascade="all, delete-orphan",
        order_by="desc(ContractUpdateHistory.created_at)",
    )
    documents = db.relationship(
        "ContractDocument",
        back_populates="contract",
        cascade="all, delete-orphan",
        order_by="desc(ContractDocument.uploaded_at)",
    )

    def days_until_end(self, today=None):
        if not self.end_date:
            return None
        today = today or datetime.utcnow().date()
        return (self.end_date - today).days

    def notice_date(self):
        if not self.end_date:
            return None
        notice_days = self.notice_period_days if self.notice_period_days is not None else 60
        return self.end_date - timedelta(days=max(notice_days, 0))

    def lifecycle_alert(self, today=None):
        today = today or datetime.utcnow().date()
        if (self.status or "").lower() == "terminated":
            return {
                "state": "terminated",
                "label": "Terminated",
                "severity": "secondary",
                "days_until_end": self.days_until_end(today),
                "notice_date": self.notice_date(),
                "needs_action": False,
            }
        if not self.end_date:
            return {
                "state": "no_end_date",
                "label": "No end date",
                "severity": "secondary",
                "days_until_end": None,
                "notice_date": None,
                "needs_action": False,
            }

        days_until_end = self.days_until_end(today)
        notice_date = self.notice_date()
        if days_until_end < 0:
            state = "expired_auto_renew" if self.auto_renew else "expired"
            label = "Expired / auto-renew" if self.auto_renew else "Expired"
            return {
                "state": state,
                "label": label,
                "severity": "danger",
                "days_until_end": days_until_end,
                "notice_date": notice_date,
                "needs_action": True,
            }
        if notice_date and today >= notice_date:
            if days_until_end <= 14:
                severity = "danger"
                state = "expires_now"
                label = "Expires soon"
            else:
                severity = "warning"
                state = "expiring_soon"
                label = "Expiring soon"
            if self.auto_renew:
                state = f"{state}_auto_renew"
                label = f"{label} / auto-renew"
            return {
                "state": state,
                "label": label,
                "severity": severity,
                "days_until_end": days_until_end,
                "notice_date": notice_date,
                "needs_action": True,
            }

        return {
            "state": "active",
            "label": "Active",
            "severity": "success",
            "days_until_end": days_until_end,
            "notice_date": notice_date,
            "needs_action": False,
        }

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
            "alert": {
                **self.lifecycle_alert(),
                "notice_date": self.notice_date().isoformat() if self.notice_date() else "",
            },
            "history": [entry.to_dict() for entry in self.history[:20]],
            "documents": [document.to_dict() for document in self.documents],
        }

    def __repr__(self):
        return f"<Contract {self.name} ({self.contract_type})>"


class ContractUpdateHistory(db.Model):
    __tablename__ = "contract_update_history"

    id = db.Column(db.Integer, primary_key=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("contract.id"), nullable=False, index=True)
    action = db.Column(db.String(50), nullable=False)
    previous_start_date = db.Column(db.Date)
    previous_end_date = db.Column(db.Date)
    new_start_date = db.Column(db.Date)
    new_end_date = db.Column(db.Date)
    previous_renewal_date = db.Column(db.Date)
    new_renewal_date = db.Column(db.Date)
    previous_status = db.Column(db.String(120))
    new_status = db.Column(db.String(120))
    previous_value = db.Column(db.Numeric(12, 2))
    new_value = db.Column(db.Numeric(12, 2))
    previous_currency = db.Column(db.String(8))
    new_currency = db.Column(db.String(8))
    changed_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    contract = db.relationship("Contract", back_populates="history")
    changed_by = db.relationship("User", foreign_keys=[changed_by_id])

    def _date_to_string(self, value):
        return value.isoformat() if value else ""

    def _date_to_display(self, value):
        return value.strftime("%d/%m/%Y") if value else ""

    def _decimal_to_string(self, value):
        if isinstance(value, Decimal):
            return str(value)
        return f"{value:.2f}" if value is not None else ""

    def to_dict(self):
        return {
            "id": self.id,
            "action": self.action,
            "previous_start_date": self._date_to_string(self.previous_start_date),
            "previous_end_date": self._date_to_string(self.previous_end_date),
            "new_start_date": self._date_to_string(self.new_start_date),
            "new_end_date": self._date_to_string(self.new_end_date),
            "previous_renewal_date": self._date_to_string(self.previous_renewal_date),
            "new_renewal_date": self._date_to_string(self.new_renewal_date),
            "previous_start_date_display": self._date_to_display(self.previous_start_date),
            "previous_end_date_display": self._date_to_display(self.previous_end_date),
            "new_start_date_display": self._date_to_display(self.new_start_date),
            "new_end_date_display": self._date_to_display(self.new_end_date),
            "previous_renewal_date_display": self._date_to_display(self.previous_renewal_date),
            "new_renewal_date_display": self._date_to_display(self.new_renewal_date),
            "previous_status": self.previous_status or "",
            "new_status": self.new_status or "",
            "previous_value": self._decimal_to_string(self.previous_value),
            "new_value": self._decimal_to_string(self.new_value),
            "previous_currency": self.previous_currency or "",
            "new_currency": self.new_currency or "",
            "changed_by": self.changed_by.username if self.changed_by else "",
            "notes": self.notes or "",
            "created_at": self.created_at.strftime("%d/%m/%Y %H:%M") if self.created_at else "",
        }


class ContractDocument(db.Model):
    __tablename__ = "contract_document"

    id = db.Column(db.Integer, primary_key=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("contract.id"), nullable=False, index=True)
    history_id = db.Column(db.Integer, db.ForeignKey("contract_update_history.id"), nullable=True, index=True)
    original_filename = db.Column(db.String(255))
    stored_filename = db.Column(db.String(255), nullable=False, unique=True)
    display_filename = db.Column(db.String(255), nullable=False)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    notes = db.Column(db.Text)

    contract = db.relationship("Contract", back_populates="documents")
    history = db.relationship("ContractUpdateHistory", backref=db.backref("documents", lazy=True))
    uploaded_by = db.relationship("User", foreign_keys=[uploaded_by_id])

    def to_dict(self):
        return {
            "id": self.id,
            "original_filename": self.original_filename or "",
            "display_filename": self.display_filename or self.stored_filename,
            "start_date": self.start_date.strftime("%d/%m/%Y") if self.start_date else "",
            "end_date": self.end_date.strftime("%d/%m/%Y") if self.end_date else "",
            "uploaded_by": self.uploaded_by.username if self.uploaded_by else "",
            "uploaded_at": self.uploaded_at.strftime("%d/%m/%Y %H:%M") if self.uploaded_at else "",
            "notes": self.notes or "",
        }
