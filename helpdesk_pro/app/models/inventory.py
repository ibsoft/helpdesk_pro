# -*- coding: utf-8 -*-
"""
Inventory models for Helpdesk Pro.
Defines software and hardware asset registries with rich metadata and
user assignment support to cover typical IT department needs.
"""

from datetime import datetime
from app import db


class SoftwareAsset(db.Model):
    __tablename__ = "software_asset"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    category = db.Column(db.String(120))
    vendor = db.Column(db.String(150))
    version = db.Column(db.String(100))
    license_type = db.Column(db.String(120))
    license_key = db.Column(db.String(255))
    serial_number = db.Column(db.String(150))
    custom_tag = db.Column(db.String(120), unique=True)
    seats = db.Column(db.Integer)
    platform = db.Column(db.String(120))
    environment = db.Column(db.String(120))
    status = db.Column(db.String(120))
    cost_center = db.Column(db.String(120))
    purchase_date = db.Column(db.Date)
    expiration_date = db.Column(db.Date)
    renewal_date = db.Column(db.Date)
    support_vendor = db.Column(db.String(150))
    support_email = db.Column(db.String(150))
    support_phone = db.Column(db.String(80))
    contract_url = db.Column(db.String(255))
    assigned_to = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    assigned_on = db.Column(db.Date)
    usage_scope = db.Column(db.String(150))
    deployment_notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    assignee = db.relationship(
        "User", foreign_keys=[assigned_to], backref="software_assets")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name or "",
            "category": self.category or "",
            "vendor": self.vendor or "",
            "version": self.version or "",
            "license_type": self.license_type or "",
            "license_key": self.license_key or "",
            "serial_number": self.serial_number or "",
            "custom_tag": self.custom_tag or "",
            "seats": self.seats or "",
            "platform": self.platform or "",
            "environment": self.environment or "",
            "status": self.status or "",
            "cost_center": self.cost_center or "",
            "purchase_date": self.purchase_date.isoformat() if self.purchase_date else "",
            "expiration_date": self.expiration_date.isoformat() if self.expiration_date else "",
            "renewal_date": self.renewal_date.isoformat() if self.renewal_date else "",
            "support_vendor": self.support_vendor or "",
            "support_email": self.support_email or "",
            "support_phone": self.support_phone or "",
            "contract_url": self.contract_url or "",
            "assigned_to": self.assigned_to,
            "assigned_to_name": self.assignee.username if self.assignee else "",
            "assigned_on": self.assigned_on.isoformat() if self.assigned_on else "",
            "usage_scope": self.usage_scope or "",
            "deployment_notes": self.deployment_notes or "",
        }

    def __repr__(self):
        return f"<SoftwareAsset {self.name} ({self.version})>"


class HardwareAsset(db.Model):
    __tablename__ = "hardware_asset"

    id = db.Column(db.Integer, primary_key=True)
    asset_tag = db.Column(db.String(120), unique=True)
    serial_number = db.Column(db.String(150))
    custom_tag = db.Column(db.String(120), unique=True)
    category = db.Column(db.String(120))
    type = db.Column(db.String(120))
    manufacturer = db.Column(db.String(150))
    model = db.Column(db.String(150))
    cpu = db.Column(db.String(150))
    ram_gb = db.Column(db.String(50))
    storage = db.Column(db.String(120))
    gpu = db.Column(db.String(150))
    operating_system = db.Column(db.String(150))
    ip_address = db.Column(db.String(50))
    mac_address = db.Column(db.String(50))
    hostname = db.Column(db.String(150))
    location = db.Column(db.String(150))
    rack = db.Column(db.String(100))
    status = db.Column(db.String(120))
    condition = db.Column(db.String(120))
    purchase_date = db.Column(db.Date)
    warranty_end = db.Column(db.Date)
    support_vendor = db.Column(db.String(150))
    support_contract = db.Column(db.String(150))
    assigned_to = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    assigned_on = db.Column(db.Date)
    accessories = db.Column(db.String(255))
    power_supply = db.Column(db.String(120))
    bios_version = db.Column(db.String(120))
    firmware_version = db.Column(db.String(120))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    assignee = db.relationship(
        "User", foreign_keys=[assigned_to], backref="hardware_assets")

    def to_dict(self):
        return {
            "id": self.id,
            "asset_tag": self.asset_tag or "",
            "serial_number": self.serial_number or "",
            "custom_tag": self.custom_tag or "",
            "category": self.category or "",
            "type": self.type or "",
            "manufacturer": self.manufacturer or "",
            "model": self.model or "",
            "cpu": self.cpu or "",
            "ram_gb": self.ram_gb or "",
            "storage": self.storage or "",
            "gpu": self.gpu or "",
            "operating_system": self.operating_system or "",
            "ip_address": self.ip_address or "",
            "mac_address": self.mac_address or "",
            "hostname": self.hostname or "",
            "location": self.location or "",
            "rack": self.rack or "",
            "status": self.status or "",
            "condition": self.condition or "",
            "purchase_date": self.purchase_date.isoformat() if self.purchase_date else "",
            "warranty_end": self.warranty_end.isoformat() if self.warranty_end else "",
            "support_vendor": self.support_vendor or "",
            "support_contract": self.support_contract or "",
            "assigned_to": self.assigned_to,
            "assigned_to_name": self.assignee.username if self.assignee else "",
            "assigned_on": self.assigned_on.isoformat() if self.assigned_on else "",
            "accessories": self.accessories or "",
            "power_supply": self.power_supply or "",
            "bios_version": self.bios_version or "",
            "firmware_version": self.firmware_version or "",
            "notes": self.notes or "",
        }

    def __repr__(self):
        return f"<HardwareAsset {self.asset_tag or self.serial_number}>"
