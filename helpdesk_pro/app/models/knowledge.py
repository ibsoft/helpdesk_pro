# -*- coding: utf-8 -*-
"""
Knowledge base models.
Provides articles with versioning and file attachments that can be searched.
"""

from datetime import datetime
import os

from sqlalchemy.orm import relationship

from app import db


class KnowledgeArticle(db.Model):
    __tablename__ = "knowledge_article"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    summary = db.Column(db.Text)
    content = db.Column(db.Text, nullable=False)
    tags = db.Column(db.String(255))
    category = db.Column(db.String(120))
    is_published = db.Column(db.Boolean, default=True)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    updated_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    versions = relationship(
        "KnowledgeArticleVersion",
        backref="article",
        cascade="all, delete-orphan",
        order_by="KnowledgeArticleVersion.version_number.desc()",
    )

    attachments = relationship(
        "KnowledgeAttachment",
        backref="article",
        cascade="all, delete-orphan",
        order_by="KnowledgeAttachment.uploaded_at.desc()",
    )

    def add_version(self, user_id):
        version = KnowledgeArticleVersion(
            article_id=self.id,
            version_number=len(self.versions) + 1,
            title=self.title,
            summary=self.summary,
            content=self.content,
            tags=self.tags,
            category=self.category,
            created_by=user_id,
        )
        db.session.add(version)
        return version

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "content": self.content,
            "tags": self.tags,
            "category": self.category,
            "is_published": self.is_published,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @property
    def search_blob(self):
        parts = [self.title or "", self.summary or "", self.content or "", self.tags or "", self.category or ""]
        for attachment in self.attachments:
            if attachment.extracted_text:
                parts.append(attachment.extracted_text)
        return "\n".join(parts)

    def __repr__(self):
        return f"<KnowledgeArticle {self.id} {self.title!r}>"


class KnowledgeArticleVersion(db.Model):
    __tablename__ = "knowledge_article_version"

    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey("knowledge_article.id", ondelete="CASCADE"), nullable=False)
    version_number = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(255), nullable=False)
    summary = db.Column(db.Text)
    content = db.Column(db.Text, nullable=False)
    tags = db.Column(db.String(255))
    category = db.Column(db.String(120))
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<KnowledgeArticleVersion {self.article_id} v{self.version_number}>"


class KnowledgeAttachment(db.Model):
    __tablename__ = "knowledge_attachment"

    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey("knowledge_article.id", ondelete="CASCADE"), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False)
    mimetype = db.Column(db.String(120))
    file_size = db.Column(db.Integer)
    extracted_text = db.Column(db.Text)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    def file_path(self, upload_folder):
        return os.path.join(upload_folder, self.stored_filename)

    def __repr__(self):
        return f"<KnowledgeAttachment {self.original_filename} ({self.article_id})>"
