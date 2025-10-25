# -*- coding: utf-8 -*-
"""
Network inventory models for Helpdesk Pro.
Keeps track of IP networks that can be further expanded with host details.
"""

from datetime import datetime
import ipaddress

from app import db


class Network(db.Model):
    __tablename__ = "network"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    cidr = db.Column(db.String(64), nullable=False, unique=True)
    description = db.Column(db.Text)
    site = db.Column(db.String(120))
    vlan = db.Column(db.String(60))
    gateway = db.Column(db.String(64))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def as_dict(self):
        return {
            "id": self.id,
            "name": self.name or "",
            "cidr": self.cidr,
            "description": self.description or "",
            "site": self.site or "",
            "vlan": self.vlan or "",
            "gateway": self.gateway or "",
            "notes": self.notes or "",
            "host_capacity": self.host_capacity,
            "network_address": self.network_address,
            "broadcast_address": self.broadcast_address,
        }

    @property
    def ip_network(self):
        try:
            return ipaddress.ip_network(self.cidr, strict=False)
        except ValueError:
            return None

    @property
    def host_capacity(self):
        network = self.ip_network
        if not network:
            return 0
        if isinstance(network, ipaddress.IPv4Network):
            return max(network.num_addresses - 2, 0) if network.prefixlen <= 30 else network.num_addresses
        return network.num_addresses

    @property
    def network_address(self):
        network = self.ip_network
        return str(network.network_address) if network else ""

    @property
    def broadcast_address(self):
        network = self.ip_network
        return str(network.broadcast_address) if network else ""

    def __repr__(self):
        return f"<Network {self.name} ({self.cidr})>"


class NetworkHost(db.Model):
    __tablename__ = "network_host"

    id = db.Column(db.Integer, primary_key=True)
    network_id = db.Column(db.Integer, db.ForeignKey("network.id", ondelete="CASCADE"), nullable=False)
    ip_address = db.Column(db.String(64), nullable=False)
    hostname = db.Column(db.String(150))
    mac_address = db.Column(db.String(50))
    device_type = db.Column(db.String(80))
    assigned_to = db.Column(db.String(150))
    description = db.Column(db.Text)
    is_reserved = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    network = db.relationship("Network", backref=db.backref("hosts", cascade="all, delete-orphan", passive_deletes=True))

    __table_args__ = (
        db.UniqueConstraint("network_id", "ip_address", name="uq_network_ip"),
    )

    def as_dict(self):
        return {
            "id": self.id,
            "network_id": self.network_id,
            "ip_address": self.ip_address,
            "hostname": self.hostname or "",
            "mac_address": self.mac_address or "",
            "device_type": self.device_type or "",
            "assigned_to": self.assigned_to or "",
            "description": self.description or "",
            "is_reserved": self.is_reserved,
        }

    def __repr__(self):
        return f"<NetworkHost {self.ip_address} (network {self.network_id})>"
