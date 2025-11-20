# -*- coding: utf-8 -*-
"""
Data models for the Fleet Monitoring module.
"""

from datetime import datetime
import os
import binascii
import hashlib

from app import db


class FleetHost(db.Model):
    __tablename__ = "fleet_host"

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(db.String(120), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(160))
    os_family = db.Column(db.String(64))
    os_version = db.Column(db.String(128))
    location = db.Column(db.String(255))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    contact = db.Column(db.String(255))
    tags = db.Column(db.String(255))
    notes = db.Column(db.Text)
    map_pin_icon = db.Column(db.String(255))
    last_seen_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    messages = db.relationship(
        "FleetMessage",
        back_populates="host",
        cascade="all, delete-orphan",
        order_by="desc(FleetMessage.ts)",
    )
    latest_state = db.relationship(
        "FleetLatestState",
        back_populates="host",
        uselist=False,
        cascade="all, delete-orphan",
    )
    screenshots = db.relationship(
        "FleetScreenshot",
        back_populates="host",
        order_by="desc(FleetScreenshot.created_at)",
        cascade="all, delete-orphan",
    )
    alerts = db.relationship(
        "FleetAlert",
        back_populates="host",
        cascade="all, delete-orphan",
        order_by="desc(FleetAlert.triggered_at)",
    )
    remote_commands = db.relationship(
        "FleetRemoteCommand",
        back_populates="host",
        cascade="all, delete-orphan",
        order_by="desc(FleetRemoteCommand.created_at)",
    )
    file_transfers = db.relationship(
        "FleetFileTransfer",
        back_populates="host",
        cascade="all, delete-orphan",
        order_by="desc(FleetFileTransfer.created_at)",
    )

    def __repr__(self):
        return f"<FleetHost agent={self.agent_id}>"


class FleetMessage(db.Model):
    __tablename__ = "fleet_message"

    id = db.Column(db.Integer, primary_key=True)
    host_id = db.Column(
        db.Integer,
        db.ForeignKey("fleet_host.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ts = db.Column(db.DateTime, nullable=False, index=True)
    category = db.Column(db.String(48), nullable=False)
    subtype = db.Column(db.String(48))
    level = db.Column(db.String(16))
    payload = db.Column(db.JSON, nullable=False)
    doc_key = db.Column(db.String(128), unique=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    host = db.relationship("FleetHost", back_populates="messages")

    def __repr__(self):
        return f"<FleetMessage host={self.host_id} ts={self.ts}>"


class FleetLatestState(db.Model):
    __tablename__ = "fleet_latest_state"

    id = db.Column(db.Integer, primary_key=True)
    host_id = db.Column(
        db.Integer,
        db.ForeignKey("fleet_host.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    snapshot = db.Column(db.JSON, nullable=False)
    screenshot_id = db.Column(db.Integer, db.ForeignKey("fleet_screenshot.id"))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    host = db.relationship("FleetHost", back_populates="latest_state")
    screenshot = db.relationship("FleetScreenshot", back_populates="latest_for_state")


class FleetScreenshot(db.Model):
    __tablename__ = "fleet_screenshot"

    id = db.Column(db.Integer, primary_key=True)
    host_id = db.Column(
        db.Integer,
        db.ForeignKey("fleet_host.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mime_type = db.Column(db.String(64), default="image/jpeg")
    data = db.Column(db.LargeBinary, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    host = db.relationship("FleetHost", back_populates="screenshots")
    latest_for_state = db.relationship("FleetLatestState", back_populates="screenshot", uselist=False)

    @property
    def data_base64(self) -> str | None:
        if not self.data:
            return None
        import base64

        encoded = base64.b64encode(self.data).decode("ascii")
        return f"data:{self.mime_type or 'image/jpeg'};base64,{encoded}"


class FleetApiKey(db.Model):
    __tablename__ = "fleet_api_key"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    key_hash = db.Column(db.String(128), nullable=False, unique=True)
    salt = db.Column(db.String(32), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    expires_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @staticmethod
    def _hash(raw: str, salt: str) -> str:
        return hashlib.sha256(f"{salt}:{raw}".encode("utf-8")).hexdigest()

    @classmethod
    def generate_key(cls) -> str:
        random_hex = binascii.hexlify(os.urandom(24)).decode("ascii")
        return f"flt-{random_hex}"

    def _split_hash_components(self) -> tuple[str, str | None, str | None]:
        token = self.key_hash or ""
        parts = token.split(":", 2)
        if len(parts) == 3:
            return parts[0], parts[1], parts[2]
        return token, None, None

    def set_key(self, raw_key: str):
        salt = binascii.hexlify(os.urandom(8)).decode("ascii")
        self.salt = salt
        hashed_value = self._hash(raw_key, salt)
        prefix_hint = raw_key[:4] if raw_key else ""
        suffix_hint = raw_key[-4:] if raw_key else ""
        self.key_hash = f"{hashed_value}:{prefix_hint}:{suffix_hint}"

    def matches(self, raw_key: str) -> bool:
        if not self.active:
            return False
        if self.expires_at and self.expires_at < datetime.utcnow():
            return False
        stored_hash, _, _ = self._split_hash_components()
        return stored_hash == self._hash(raw_key, self.salt)

    @property
    def prefix_hint(self) -> str | None:
        _, prefix, _ = self._split_hash_components()
        return prefix

    @property
    def suffix_hint(self) -> str | None:
        _, _, suffix = self._split_hash_components()
        return suffix

    @property
    def masked_hint(self) -> str | None:
        prefix = self.prefix_hint
        suffix = self.suffix_hint
        if not prefix and not suffix:
            return None
        prefix_display = prefix or "••••"
        suffix_display = suffix or "••••"
        return f"{prefix_display}\u2026{suffix_display}"


class FleetModuleSettings(db.Model):
    __tablename__ = "fleet_module_settings"

    id = db.Column(db.Integer, primary_key=True, default=1)
    map_zoom = db.Column(db.Integer, default=5, nullable=False)
    map_pin_icon = db.Column(db.String(255), default="fa-map-pin")
    retention_days_messages = db.Column(db.Integer, default=60, nullable=False)
    retention_days_screenshots = db.Column(db.Integer, default=30, nullable=False)
    show_dashboard_screenshots = db.Column(db.Boolean, default=True, nullable=False)
    default_alert_rules = db.Column(db.JSON, default=dict, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    @classmethod
    def get(cls) -> "FleetModuleSettings":
        instance = cls.query.get(1)
        if not instance:
            instance = cls()
            db.session.add(instance)
            db.session.commit()
        if not instance.default_alert_rules:
            instance.default_alert_rules = {
                "cpu": {"threshold": 90},
                "disk": {"threshold": 85},
                "antivirus": {"enabled": True},
                "updates": {"pending": 0},
                "events": {"errors24h": 0},
            }
            db.session.commit()
        return instance


class FleetAgentDownloadLink(db.Model):
    __tablename__ = "fleet_agent_download_link"

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(96), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime)
    revoked_at = db.Column(db.DateTime)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))

    created_by_user = db.relationship("User")

    @property
    def is_expired(self) -> bool:
        return bool(self.expires_at and self.expires_at < datetime.utcnow())

    @property
    def is_active(self) -> bool:
        return not self.revoked_at and not self.is_expired


class FleetAlert(db.Model):
    __tablename__ = "fleet_alert"

    id = db.Column(db.Integer, primary_key=True)
    host_id = db.Column(
        db.Integer,
        db.ForeignKey("fleet_host.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rule_key = db.Column(db.String(64), nullable=False, index=True)
    severity = db.Column(db.String(16), nullable=False, default="warning")
    message = db.Column(db.Text, nullable=False)
    triggered_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    resolved_at = db.Column(db.DateTime)

    host = db.relationship("FleetHost", back_populates="alerts")

    @property
    def active(self) -> bool:
        return self.resolved_at is None


class FleetRemoteCommand(db.Model):
    __tablename__ = "fleet_remote_command"

    id = db.Column(db.Integer, primary_key=True)
    host_id = db.Column(
        db.Integer,
        db.ForeignKey("fleet_host.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    issued_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    command = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(32), nullable=False, default="pending")
    response = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    delivered_at = db.Column(db.DateTime)
    executed_at = db.Column(db.DateTime)
    source_job_id = db.Column(
        db.Integer,
        db.ForeignKey("fleet_scheduled_job.id", ondelete="SET NULL"),
        nullable=True,
    )

    host = db.relationship("FleetHost", back_populates="remote_commands")
    issued_by = db.relationship("User")
    source_job = db.relationship("FleetScheduledJob")


class FleetFileTransfer(db.Model):
    __tablename__ = "fleet_file_transfer"

    id = db.Column(db.Integer, primary_key=True)
    host_id = db.Column(
        db.Integer,
        db.ForeignKey("fleet_host.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uploaded_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    stored_path = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(128))
    size_bytes = db.Column(db.Integer)
    checksum = db.Column(db.String(128))
    source_job_id = db.Column(
        db.Integer,
        db.ForeignKey("fleet_scheduled_job.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    consumed_at = db.Column(db.DateTime)

    host = db.relationship("FleetHost", back_populates="file_transfers")
    uploaded_by = db.relationship("User")
    source_job = db.relationship("FleetScheduledJob", back_populates="transfers")


class FleetScheduledJob(db.Model):
    __tablename__ = "fleet_scheduled_job"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    action_type = db.Column(db.String(32), nullable=False, default="command")
    status = db.Column(db.String(32), nullable=False, default="scheduled")
    run_at = db.Column(db.DateTime, nullable=False)
    recurrence = db.Column(db.String(32), nullable=False, default="once")
    target_hosts = db.Column(db.JSON, nullable=False, default=list)
    payload = db.Column(db.JSON, nullable=False, default=dict)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    created_by = db.relationship("User")
    transfers = db.relationship("FleetFileTransfer", back_populates="source_job", cascade="all, delete-orphan")

    def target_count(self) -> int:
        if isinstance(self.target_hosts, list):
            return len(self.target_hosts)
        return 0
