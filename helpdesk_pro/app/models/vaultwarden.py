from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB

from app import db

ITEM_TYPES = [
    ("login", "Login"),
    ("secure_note", "Secure note"),
    ("card", "Card"),
    ("identity", "Identity"),
    ("custom", "Custom item"),
]


class VaultFolder(db.Model):
    __tablename__ = "vault_folder"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    name = db.Column(db.String(180), nullable=False)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("vault_organization.id", ondelete="SET NULL"),
        nullable=True,
    )
    collection_id = db.Column(
        db.Integer,
        db.ForeignKey("vault_collection.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    user = relationship("User", backref="vault_folders")
    organization = relationship("VaultOrganization")
    collection = relationship("VaultCollection")

    def __repr__(self):
        return f"<VaultFolder id={self.id} name={self.name}>"


class VaultOrganization(db.Model):
    __tablename__ = "vault_organization"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(180), nullable=False)
    slug = db.Column(db.String(180), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    key_ciphertext = db.Column(db.Text, nullable=True)
    key_version = db.Column(db.Integer, nullable=False, default=1)
    key_created_at = db.Column(db.DateTime, nullable=True)

    created_by = relationship("User", foreign_keys=[created_by_user_id])
    memberships = relationship("VaultOrganizationMembership", back_populates="organization", cascade="all, delete-orphan")
    collections = relationship("VaultCollection", back_populates="organization", cascade="all, delete-orphan")
    key_shares = relationship("VaultOrganizationKeyShare", back_populates="organization", cascade="all, delete-orphan")

    def assign_key(self, ciphertext: str, version: int) -> None:
        self.key_ciphertext = ciphertext
        self.key_version = version
        self.key_created_at = datetime.utcnow()

    def __repr__(self):
        return f"<VaultOrganization id={self.id} name={self.name}>"


class VaultOrganizationMembership(db.Model):
    __tablename__ = "vault_organization_membership"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("vault_organization.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    role = db.Column(db.String(40), nullable=False, default="member")
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())

    organization = relationship("VaultOrganization", back_populates="memberships")
    user = relationship("User")

    def __repr__(self):
        return f"<VaultOrgMembership user={self.user_id} org={self.organization_id} role={self.role}>"


class VaultCollection(db.Model):
    __tablename__ = "vault_collection"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("vault_organization.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    organization = relationship("VaultOrganization", back_populates="collections")
    access_controls = relationship(
        "VaultCollectionAccess",
        back_populates="collection",
        cascade="all, delete-orphan",
    )
    items = relationship("VaultItem", back_populates="collection")

    def __repr__(self):
        return f"<VaultCollection id={self.id} name={self.name}>"


class VaultItem(db.Model):
    __tablename__ = "vault_item"

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey("vault_organization.id"), nullable=True)
    collection_id = db.Column(db.Integer, db.ForeignKey("vault_collection.id"), nullable=True)
    folder_id = db.Column(db.Integer, db.ForeignKey("vault_folder.id"), nullable=True)
    name = db.Column(db.String(255), nullable=False)
    item_type = db.Column(db.String(50), nullable=False)
    favorite = db.Column(db.Boolean, nullable=False, default=False)
    trashed = db.Column(db.Boolean, nullable=False, default=False)
    tags = db.Column(JSONB, nullable=False, default=list)
    encrypted_blob = db.Column(JSONB, nullable=False)
    metadata_blob = db.Column(JSONB, nullable=False, default=dict)
    version = db.Column(db.Integer, nullable=False, default=1)
    password_history = db.Column(JSONB, nullable=False, default=list)
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    last_accessed = db.Column(db.DateTime, nullable=True)

    owner = relationship("User", backref="vault_items")
    organization = relationship("VaultOrganization")
    collection = relationship("VaultCollection", back_populates="items")
    folder = relationship("VaultFolder")
    shares = relationship("VaultItemShare", back_populates="item", cascade="all, delete-orphan")
    attachments = relationship("VaultAttachment", back_populates="item", cascade="all, delete-orphan")

    @property
    def tag_list(self) -> list[str]:
        if isinstance(self.tags, list):
            return [str(tag) for tag in self.tags if tag]
        return []

    def __repr__(self):
        return f"<VaultItem id={self.id} name={self.name}>"


class VaultItemShare(db.Model):
    __tablename__ = "vault_item_share"

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("vault_item.id", ondelete="CASCADE"), nullable=False)
    shared_with_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    shared_with_collection_id = db.Column(db.Integer, db.ForeignKey("vault_collection.id"), nullable=True)
    access_level = db.Column(db.String(32), nullable=False, default="read")
    expires_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())

    item = relationship("VaultItem", back_populates="shares")
    shared_with_user = relationship("User", foreign_keys=[shared_with_user_id])
    shared_with_collection = relationship("VaultCollection")

    def __repr__(self):
        return f"<VaultItemShare id={self.id} access={self.access_level}>"


class VaultAttachment(db.Model):
    __tablename__ = "vault_attachment"

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("vault_item.id", ondelete="CASCADE"), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(120), nullable=True)
    size = db.Column(db.Integer, nullable=False, default=0)
    storage_path = db.Column(db.String(512), nullable=True)
    encrypted_blob = db.Column(db.JSON, nullable=False)
    uploaded_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())

    item = relationship("VaultItem", back_populates="attachments")
    uploaded_by = relationship("User", foreign_keys=[uploaded_by_user_id])

    def __repr__(self):
        return f"<VaultAttachment id={self.id} file={self.filename}>"


class VaultAuditLog(db.Model):
    __tablename__ = "vault_audit_log"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey("vault_organization.id"), nullable=True)
    item_id = db.Column(db.Integer, db.ForeignKey("vault_item.id"), nullable=True)
    action = db.Column(db.String(80), nullable=False)
    details = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())

    @classmethod
    def record(cls, action: str, *, user_id: int, organization_id: Optional[int] = None, item_id: Optional[int] = None, details: Optional[dict] = None):
        entry = cls(
            user_id=user_id,
            organization_id=organization_id,
            item_id=item_id,
            action=action,
            details=details or {},
        )
        db.session.add(entry)

    def __repr__(self):
        return f"<VaultAuditLog action={self.action} user={self.user_id}>"


class VaultOrganizationKeyShare(db.Model):
    __tablename__ = "vault_organization_key_share"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("vault_organization.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    key_blob = db.Column(db.Text, nullable=False)
    version = db.Column(db.Integer, nullable=False, default=1)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())
    expires_at = db.Column(db.DateTime, nullable=True)

    organization = relationship("VaultOrganization", back_populates="key_shares")
    user = relationship("User", foreign_keys=[user_id])
    created_by = relationship("User", foreign_keys=[created_by_user_id])

    def __repr__(self):
        return f"<VaultOrganizationKeyShare org={self.organization_id} user={self.user_id} v={self.version}>"


class VaultCollectionAccess(db.Model):
    __tablename__ = "vault_collection_access"

    id = db.Column(db.Integer, primary_key=True)
    collection_id = db.Column(
        db.Integer,
        db.ForeignKey("vault_collection.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    access_level = db.Column(db.String(32), nullable=False, default="read")
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())

    collection = relationship("VaultCollection", back_populates="access_controls")
    user = relationship("User", foreign_keys=[user_id])
    created_by = relationship("User", foreign_keys=[created_by_user_id])

    __table_args__ = (
        db.UniqueConstraint("collection_id", "user_id", name="uq_collection_user_access"),
    )

    def __repr__(self):
        return f"<VaultCollectionAccess coll={self.collection_id} user={self.user_id} level={self.access_level}>"
