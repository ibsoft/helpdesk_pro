# -*- coding: utf-8 -*-
"""
Authentication configuration model.
Controls self-service registration and password reset features.
"""

from datetime import datetime
from typing import Optional, Dict, Any

from app import db
from app.navigation import AVAILABLE_ROLES


class AuthConfig(db.Model):
    __tablename__ = "auth_config"

    id = db.Column(db.Integer, primary_key=True)
    allow_self_registration = db.Column(db.Boolean, default=False, nullable=False)
    allow_password_reset = db.Column(db.Boolean, default=False, nullable=False)
    default_role = db.Column(db.String(20), default="user", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get(cls) -> Optional["AuthConfig"]:
        return cls.query.order_by(cls.id.asc()).first()

    @classmethod
    def load(cls) -> "AuthConfig":
        instance = cls.get()
        if not instance:
            instance = cls()
            if instance.default_role not in AVAILABLE_ROLES:
                instance.default_role = "user"
            db.session.add(instance)
            db.session.commit()
        return instance

    def ensure_valid_role(self):
        if self.default_role not in AVAILABLE_ROLES:
            self.default_role = "user"

    def to_dict(self) -> Dict[str, Any]:
        self.ensure_valid_role()
        return {
            "allow_self_registration": bool(self.allow_self_registration),
            "allow_password_reset": bool(self.allow_password_reset),
            "default_role": self.default_role,
        }
