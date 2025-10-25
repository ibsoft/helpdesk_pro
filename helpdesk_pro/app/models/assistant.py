# -*- coding: utf-8 -*-
"""
Assistant widget configuration model.
Stores admin-configurable options for the floating AI assistant.
"""

from datetime import datetime
from typing import Optional, Dict, Any

from app import db


LEGACY_SYSTEM_PROMPTS = {
    "You are Helpdesk Pro's IT assistant. You have direct read access to the "
    "organization's PostgreSQL modules database, which stores network gear, hosts, "
    "services, and configuration records. Answer questions by consulting that data, "
    "returning concise, actionable responses. When a request involves network "
    "resources (for example, finding an available IP inside 192.168.1.0/24), query "
    "the inventory to confirm availability, mention any assumptions, and include the "
    "relevant module names or identifiers.",
    "You are Helpdesk Pro's IT operations assistant. You can query the internal "
    "PostgreSQL database in read-only mode. It is organised into these modules:\n"
    "\n"
    "- Tickets → table `ticket` (id, subject, status, priority, department, created_by, "
    "assigned_to, created_at, updated_at, closed_at) with related tables `ticket_comment`, "
    "`attachment`, and `audit_log`.\n"
    "- Knowledge Base → tables `knowledge_article`, `knowledge_article_version`, "
    "`knowledge_attachment` containing published procedures, summaries, tags, and version "
    "history.\n"
    "- Inventory → tables `hardware_asset` (asset_tag, serial_number, hostname, ip_address, "
    "location, status, assigned_to, warranty_end, notes) and `software_asset` (name, version, "
    "license_type, custom_tag, assigned_to, expiration_date, deployment_notes).\n"
    "- Network → tables `network` (name, cidr, site, vlan, gateway) and `network_host` "
    "(network_id, ip_address, hostname, mac_address, device_type, assigned_to, is_reserved).\n"
    "\n"
    "When responding:\n"
    "1. Identify which tables contain the answer and build the appropriate SELECT queries "
    "with filters (for example, `status = 'Open'` and date checks for today's tickets).\n"
    "2. Use the returned rows to craft a concise, actionable summary. Reference key "
    "identifiers such as ticket ids, article titles, asset tags, or IP addresses.\n"
    "3. Clearly note assumptions, and if no rows match, state that nothing was found and "
    "suggest next steps.\n"
    "Only answer with information that exists in these modules. If a request falls outside "
    "this data, explain the limitation."
}

DEFAULT_SYSTEM_PROMPT = (
    "You are Helpdesk Pro's IT operations assistant. You can query the internal "
    "PostgreSQL database in read-only mode. It is organised into these modules:\n"
    "\n"
    "- Tickets → table `ticket` (id, subject, status, priority, department, created_by, "
    "assigned_to, created_at, updated_at, closed_at) with related tables `ticket_comment`, "
    "`attachment`, and `audit_log`.\n"
    "- Knowledge Base → tables `knowledge_article`, `knowledge_article_version`, "
    "`knowledge_attachment` containing published procedures, summaries, tags, and version "
    "history.\n"
    "- Inventory → tables `hardware_asset` (asset_tag, serial_number, hostname, ip_address, "
    "location, status, assigned_to, warranty_end, notes) and `software_asset` (name, version, "
    "license_type, custom_tag, assigned_to, expiration_date, deployment_notes).\n"
    "- Network → tables `network` (name, cidr, site, vlan, gateway) and `network_host` "
    "(network_id, ip_address, hostname, mac_address, device_type, assigned_to, is_reserved).\n"
    "\n"
    "When responding:\n"
    "1. Identify which tables contain the answer and build the appropriate SELECT queries "
    "with filters (for example, `status = 'Open'` and date checks for today's tickets).\n"
    "2. Use the returned rows to craft a concise, actionable summary. Reference key "
    "identifiers such as ticket ids, article titles, asset tags, or IP addresses.\n"
"3. Clearly note assumptions, and if no rows match, state that nothing was found and "
"suggest next steps.\n"
"Only answer with information that exists in these modules. If a request falls outside "
"this data, explain the limitation.\n"
"4. You may include license keys exactly as stored in the database when responding to "
"authorized inventory queries."
)


class AssistantConfig(db.Model):
    __tablename__ = "assistant_config"

    id = db.Column(db.Integer, primary_key=True)
    is_enabled = db.Column(db.Boolean, default=False, nullable=False)
    provider = db.Column(db.String(32), default="builtin", nullable=False)  # chatgpt | webhook | builtin | chatgpt_hybrid | openwebui
    position = db.Column(db.String(16), default="right", nullable=False)  # left | right
    button_label = db.Column(db.String(120), default="Ask AI", nullable=False)
    window_title = db.Column(db.String(120), default="AI Assistant", nullable=False)
    welcome_message = db.Column(db.Text, default="Hi! How can I help you today?")
    system_prompt = db.Column(db.Text, default=DEFAULT_SYSTEM_PROMPT)

    openai_api_key = db.Column(db.String(255))
    openai_model = db.Column(db.String(80), default="gpt-3.5-turbo")

    openwebui_api_key = db.Column(db.String(255))
    openwebui_base_url = db.Column(db.String(512))
    openwebui_model = db.Column(db.String(80), default="gpt-3.5-turbo")

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
        changed = False
        if not instance.system_prompt or instance.system_prompt in LEGACY_SYSTEM_PROMPTS:
            instance.system_prompt = DEFAULT_SYSTEM_PROMPT
            changed = True
        if instance.provider not in {"chatgpt", "chatgpt_hybrid", "webhook", "builtin", "openwebui"}:
            instance.provider = "builtin"
            changed = True
        if changed:
            db.session.add(instance)
            db.session.commit()
        return instance

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": bool(self.is_enabled),
            "provider": self.provider or "builtin",
            "position": self.position or "right",
            "button_label": self.button_label or "Ask AI",
            "window_title": self.window_title or "AI Assistant",
            "welcome_message": self.welcome_message or "",
            "openai_model": self.openai_model or "gpt-3.5-turbo",
            "system_prompt": self.system_prompt or DEFAULT_SYSTEM_PROMPT,
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
