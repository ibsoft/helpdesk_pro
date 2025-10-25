# -*- coding: utf-8 -*-
"""
REST API client credential model.
Handles key generation, rotation, and verification for external integrations.
"""

from datetime import datetime
import secrets
import bcrypt

from app import db


class ApiClient(db.Model):
    __tablename__ = "api_client"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    prefix = db.Column(db.String(16), nullable=False, unique=True)
    key_hash = db.Column(db.String(128), nullable=False)
    default_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    description = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = db.Column(db.DateTime)
    revoked_at = db.Column(db.DateTime)

    default_user = db.relationship("User")

    KEY_PREFIX = "hp"

    def is_active(self) -> bool:
        return self.revoked_at is None

    @staticmethod
    def _generate_secret() -> str:
        # token_urlsafe(32) yields ~256 bits.
        return secrets.token_urlsafe(32)

    @classmethod
    def generate_plain_key(cls) -> tuple[str, str, str]:
        """
        Return tuple (full_key, prefix, secret).
        Full key is in the form hp_<prefix>_<secret>.
        """
        prefix = secrets.token_hex(6)
        secret = cls._generate_secret()
        full = f"{cls.KEY_PREFIX}_{prefix}_{secret}"
        return full, prefix, secret

    def assign_new_secret(self) -> str:
        """
        Generate and assign a brand-new key to this client.
        Returns the plain text key so it can be shown once to the admin.
        """
        full_key, prefix, _ = self.generate_plain_key()
        self.prefix = prefix
        self.key_hash = bcrypt.hashpw(full_key.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        self.revoked_at = None
        db.session.add(self)
        return full_key

    def revoke(self):
        self.revoked_at = datetime.utcnow()
        db.session.add(self)

    @classmethod
    def verify_key(cls, raw_key: str) -> "ApiClient | None":
        if not raw_key:
            return None
        parts = raw_key.split("_", 2)
        if len(parts) != 3 or parts[0] != cls.KEY_PREFIX:
            return None
        prefix = parts[1]
        candidate = cls.query.filter_by(prefix=prefix).first()
        if not candidate or not candidate.is_active():
            return None
        if bcrypt.checkpw(raw_key.encode("utf-8"), candidate.key_hash.encode("utf-8")):
            candidate.last_used_at = datetime.utcnow()
            db.session.add(candidate)
            return candidate
        return None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "prefix": self.prefix,
            "default_user_id": self.default_user_id,
            "default_user": self.default_user.username if self.default_user else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
        }

