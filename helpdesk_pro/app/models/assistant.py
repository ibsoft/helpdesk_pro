# -*- coding: utf-8 -*-
"""
Assistant widget configuration model.
Stores admin-configurable options for the floating AI assistant.
"""

from datetime import datetime
from typing import Optional, Dict, Any

from app import db


class AssistantConfig(db.Model):
    __tablename__ = "assistant_config"

    id = db.Column(db.Integer, primary_key=True)
    is_enabled = db.Column(db.Boolean, default=False, nullable=False)
    provider = db.Column(db.String(32), default="webhook", nullable=False)  # chatgpt | webhook
    position = db.Column(db.String(16), default="right", nullable=False)  # left | right
    button_label = db.Column(db.String(120), default="Ask AI", nullable=False)
    window_title = db.Column(db.String(120), default="AI Assistant", nullable=False)
    welcome_message = db.Column(db.Text, default="Hi! How can I help you today?")

    openai_api_key = db.Column(db.String(255))
    openai_model = db.Column(db.String(80), default="gpt-3.5-turbo")

    webhook_url = db.Column(db.String(512))
    webhook_method = db.Column(db.String(10), default="POST")
    webhook_headers = db.Column(db.Text)  # JSON blob stored as text

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get(cls) -> Optional["AssistantConfig"]:
        return cls.query.order_by(cls.id.asc()).first()

    @classmethod
    def load(cls) -> "AssistantConfig":
        instance = cls.get()
        if not instance:
            instance = cls()
            db.session.add(instance)
            db.session.commit()
        return instance

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": bool(self.is_enabled),
            "provider": self.provider or "webhook",
            "position": self.position or "right",
            "button_label": self.button_label or "Ask AI",
            "window_title": self.window_title or "AI Assistant",
            "welcome_message": self.welcome_message or "",
            "openai_model": self.openai_model or "gpt-3.5-turbo",
        }

    def webhook_headers_data(self) -> Dict[str, str]:
        if not self.webhook_headers:
            return {}
        try:
            import json
            parsed = json.loads(self.webhook_headers)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
