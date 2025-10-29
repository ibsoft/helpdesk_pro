# -*- coding: utf-8 -*-
"""
Module level permissions.
Stores per-role access levels (read vs write) for specific application modules.
"""

from datetime import datetime
from app import db


class ModulePermission(db.Model):
    __tablename__ = "module_permission"

    id = db.Column(db.Integer, primary_key=True)
    module_key = db.Column(db.String(64), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    access_level = db.Column(db.String(16), nullable=False, default="write")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("module_key", "role", name="uq_module_permission_role"),
    )

    def __repr__(self):
        return f"<ModulePermission {self.module_key} role={self.role} level={self.access_level}>"
