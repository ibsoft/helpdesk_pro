# -*- coding: utf-8 -*-
"""
Collaboration (chat) models.
Provide conversations, messages, attachments, read receipts, and favorites.
"""

from datetime import datetime
import os

from app import db
from app.utils.security import encrypt_secret, decrypt_secret


class ChatConversation(db.Model):
    __tablename__ = "chat_conversation"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150))
    is_direct = db.Column(db.Boolean, default=False)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    members = db.relationship(
        "ChatMembership",
        backref="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    messages = db.relationship(
        "ChatMessage",
        backref="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ChatMessage.created_at.asc()",
    )

    def __repr__(self):
        return f"<ChatConversation {self.id} direct={self.is_direct}>"


class ChatMembership(db.Model):
    __tablename__ = "chat_membership"

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(
        db.Integer,
        db.ForeignKey("chat_conversation.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("conversation_id", "user_id", name="uq_chat_membership"),
    )

    def __repr__(self):
        return f"<ChatMembership conversation={self.conversation_id} user={self.user_id}>"


class ChatMessage(db.Model):
    __tablename__ = "chat_message"

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(
        db.Integer,
        db.ForeignKey("chat_conversation.id", ondelete="CASCADE"),
        nullable=False,
    )
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    _body = db.Column("body", db.Text)
    attachment_filename = db.Column(db.String(255))
    attachment_original = db.Column(db.String(255))
    attachment_mimetype = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    reads = db.relationship(
        "ChatMessageRead",
        backref="message",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def body(self):
        raw = self._body
        if not raw:
            return ""
        try:
            return decrypt_secret(raw)
        except Exception:
            return raw

    @body.setter
    def body(self, value):
        if value is None:
            self._body = None
            return
        text = value if isinstance(value, str) else str(value)
        self._body = encrypt_secret(text)

    def attachment_path(self, upload_folder):
        if not self.attachment_filename:
            return None
        return os.path.join(upload_folder, self.attachment_filename)

    def __repr__(self):
        return f"<ChatMessage {self.id} conv={self.conversation_id}>"


class ChatMessageRead(db.Model):
    __tablename__ = "chat_message_read"

    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(
        db.Integer,
        db.ForeignKey("chat_message.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    read_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("message_id", "user_id", name="uq_chat_message_read"),
    )

    def __repr__(self):
        return f"<ChatMessageRead message={self.message_id} user={self.user_id}>"


class ChatFavorite(db.Model):
    __tablename__ = "chat_favorite"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    favorite_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("user_id", "favorite_user_id", name="uq_chat_favorite"),
    )

    def __repr__(self):
        return f"<ChatFavorite {self.user_id}->{self.favorite_user_id}>"
