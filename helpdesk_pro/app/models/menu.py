# -*- coding: utf-8 -*-
"""
Menu permission models.
Allows storing overrides for navigation menu visibility per role or user.
"""

from datetime import datetime
from app import db


class MenuPermission(db.Model):
    __tablename__ = "menu_permission"

    id = db.Column(db.Integer, primary_key=True)
    menu_key = db.Column(db.String(64), nullable=False)
    role = db.Column(db.String(20))
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    allowed = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("menu_key", "role", "user_id", name="uq_menu_permission"),
    )

    def __repr__(self):
        return f"<MenuPermission {self.menu_key} role={self.role} user={self.user_id} allowed={self.allowed}>"
