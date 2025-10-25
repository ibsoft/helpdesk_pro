# -*- coding: utf-8 -*-
"""
Knowledge base blueprint routes.
Provides article list, detail, CRUD, versioning, and attachments.
"""

import os
import uuid
import mimetypes

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    current_app,
    send_from_directory,
)
from flask_login import login_required, current_user
from sqlalchemy import or_, func
from werkzeug.utils import secure_filename
from flask_babel import gettext as _

from app import db
from app.models import KnowledgeArticle, KnowledgeArticleVersion, KnowledgeAttachment


knowledge_bp = Blueprint("knowledge", __name__, url_prefix="/knowledge")


def _ensure_upload_folder():
    upload_folder = current_app.config.get("KNOWLEDGE_UPLOAD_FOLDER")
    if not upload_folder:
        upload_folder = os.path.join(current_app.instance_path, "knowledge_uploads")
        current_app.config["KNOWLEDGE_UPLOAD_FOLDER"] = upload_folder
    os.makedirs(upload_folder, exist_ok=True)
    return upload_folder


def _extract_text(file_path, mimetype):
    try:
        if mimetype and mimetype.startswith("text/"):
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        if mimetype in {"application/json", "application/xml"}:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
    except Exception:
        return None
    return None


def _require_editor():
    if not current_user.is_authenticated:
        return False
    return current_user.role in ["admin", "manager", "technician"]


@knowledge_bp.route("/")
@login_required
def list_articles():
    base_query = KnowledgeArticle.query.filter_by(is_published=True)
    search = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    tag = request.args.get("tag", "").strip()
    page = max(request.args.get("page", 1, type=int) or 1, 1)
    per_page = 100

    if search:
        like_term = f"%{search}%"
        base_query = (
            base_query.outerjoin(KnowledgeAttachment)
            .filter(
                or_(
                    KnowledgeArticle.title.ilike(like_term),
                    KnowledgeArticle.summary.ilike(like_term),
                    KnowledgeArticle.content.ilike(like_term),
                    KnowledgeArticle.tags.ilike(like_term),
                    KnowledgeAttachment.extracted_text.ilike(like_term),
                    KnowledgeAttachment.original_filename.ilike(like_term),
                )
            )
            .distinct()
        )
    if category:
        base_query = base_query.filter(KnowledgeArticle.category == category)
    if tag:
        base_query = base_query.filter(KnowledgeArticle.tags.ilike(f"%{tag}%"))

    pagination = (
        base_query.order_by(KnowledgeArticle.updated_at.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )
    articles = pagination.items
    category_rows = db.session.query(KnowledgeArticle.category).distinct().all()
    categories = [c[0] for c in category_rows if c[0]]

    tag_rows = db.session.query(KnowledgeArticle.tags).filter(KnowledgeArticle.tags.isnot(None)).all()
    tag_set = {
        tag.strip()
        for row in tag_rows
        for tag in (row[0] or "").split(",")
        if tag and tag.strip()
    }

    knowledge_stats = {
        "total": db.session.query(func.count(KnowledgeArticle.id)).scalar() or 0,
        "published": db.session.query(func.count(KnowledgeArticle.id)).filter(KnowledgeArticle.is_published.is_(True)).scalar() or 0,
        "drafts": db.session.query(func.count(KnowledgeArticle.id)).filter(KnowledgeArticle.is_published.is_(False)).scalar() or 0,
        "categories": len(categories),
        "tags": len(tag_set),
        "attachments": db.session.query(func.count(KnowledgeAttachment.id)).scalar() or 0,
    }

    pagination_args = {k: v for k, v in request.args.items() if k != "page" and v}

    return render_template(
        "knowledge/list.html",
        articles=articles,
        search=search,
        categories=categories,
        tags=sorted(tag_set),
        can_edit=_require_editor(),
        knowledge_stats=knowledge_stats,
        pagination=pagination,
        pagination_args=pagination_args,
        per_page=per_page,
    )


@knowledge_bp.route("/article/<int:article_id>")
@login_required
def view_article(article_id):
    article = KnowledgeArticle.query.get_or_404(article_id)
    if not article.is_published and not _require_editor():
        flash(_("You do not have access to this article."), "warning")
        return redirect(url_for("knowledge.list_articles"))
    return render_template(
        "knowledge/detail.html",
        article=article,
        can_edit=_require_editor(),
    )


@knowledge_bp.route("/article/new", methods=["GET", "POST"])
@login_required
def create_article():
    if not _require_editor():
        flash(_("You do not have permission to create articles."), "warning")
        return redirect(url_for("knowledge.list_articles"))

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        summary = request.form.get("summary")
        content = request.form.get("content")
        tags = request.form.get("tags")
        category = request.form.get("category")
        is_published = bool(request.form.get("is_published"))

        if not title or not content:
            flash(_("Title and content are required."), "warning")
            return render_template("knowledge/edit.html", article=None, can_edit=True)

        article = KnowledgeArticle(
            title=title,
            summary=summary,
            content=content,
            tags=tags,
            category=category,
            is_published=is_published,
            created_by=current_user.id,
            updated_by=current_user.id,
        )
        db.session.add(article)
        db.session.flush()
        article.add_version(current_user.id)
        db.session.commit()
        flash(_("Article created successfully."), "success")
        return redirect(url_for("knowledge.view_article", article_id=article.id))

    return render_template("knowledge/edit.html", article=None, can_edit=True)


@knowledge_bp.route("/article/<int:article_id>/edit", methods=["GET", "POST"])
@login_required
def edit_article(article_id):
    if not _require_editor():
        flash(_("You do not have permission to edit articles."), "warning")
        return redirect(url_for("knowledge.list_articles"))

    article = KnowledgeArticle.query.get_or_404(article_id)
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        summary = request.form.get("summary")
        content = request.form.get("content")
        tags = request.form.get("tags")
        category = request.form.get("category")
        is_published = bool(request.form.get("is_published"))

        if not title or not content:
            flash(_("Title and content are required."), "warning")
            return render_template("knowledge/edit.html", article=article, can_edit=True)

        article.title = title
        article.summary = summary
        article.content = content
        article.tags = tags
        article.category = category
        article.is_published = is_published
        article.updated_by = current_user.id
        article.add_version(current_user.id)
        db.session.commit()
        flash(_("Article updated successfully."), "success")
        return redirect(url_for("knowledge.view_article", article_id=article.id))

    return render_template("knowledge/edit.html", article=article, can_edit=True)


@knowledge_bp.route("/article/<int:article_id>/delete", methods=["POST"])
@login_required
def delete_article(article_id):
    if not _require_editor():
        flash(_("You do not have permission to delete articles."), "warning")
        return redirect(url_for("knowledge.list_articles"))
    article = KnowledgeArticle.query.get_or_404(article_id)
    db.session.delete(article)
    db.session.commit()
    flash(_("Article deleted."), "warning")
    return redirect(url_for("knowledge.list_articles"))


@knowledge_bp.route("/article/<int:article_id>/upload", methods=["POST"])
@login_required
def upload_attachment(article_id):
    if not _require_editor():
        flash(_("You do not have permission to upload attachments."), "warning")
        return redirect(url_for("knowledge.view_article", article_id=article_id))

    article = KnowledgeArticle.query.get_or_404(article_id)
    file = request.files.get("attachment")
    if not file or file.filename == "":
        flash(_("Please select a file to upload."), "warning")
        return redirect(url_for("knowledge.view_article", article_id=article.id))

    filename = secure_filename(file.filename)
    if not filename:
        flash(_("Invalid filename."), "danger")
        return redirect(url_for("knowledge.view_article", article_id=article.id))

    upload_folder = _ensure_upload_folder()
    unique_name = f"{uuid.uuid4().hex}_{filename}"
    stored_path = os.path.join(upload_folder, unique_name)
    file.save(stored_path)
    mimetype = file.mimetype or mimetypes.guess_type(filename)[0]
    try:
        size = os.path.getsize(stored_path)
    except OSError:
        size = None

    extracted_text = _extract_text(stored_path, mimetype)

    attachment = KnowledgeAttachment(
        article_id=article.id,
        original_filename=filename,
        stored_filename=unique_name,
        mimetype=mimetype,
        file_size=size,
        extracted_text=extracted_text,
        uploaded_by=current_user.id,
    )
    db.session.add(attachment)
    db.session.commit()
    flash(_("Attachment uploaded."), "success")
    return redirect(url_for("knowledge.view_article", article_id=article.id))


@knowledge_bp.route("/article/<int:article_id>/attachment/<int:attachment_id>/delete", methods=["POST"])
@login_required
def delete_attachment(article_id, attachment_id):
    if not _require_editor():
        flash(_("You do not have permission to delete attachments."), "warning")
        return redirect(url_for("knowledge.view_article", article_id=article_id))

    attachment = KnowledgeAttachment.query.filter_by(id=attachment_id, article_id=article_id).first_or_404()
    upload_folder = _ensure_upload_folder()
    file_path = os.path.join(upload_folder, attachment.stored_filename)
    if os.path.exists(file_path):
        os.remove(file_path)
    db.session.delete(attachment)
    db.session.commit()
    flash(_("Attachment removed."), "warning")
    return redirect(url_for("knowledge.view_article", article_id=article_id))


@knowledge_bp.route("/attachments/<path:filename>")
@login_required
def download_attachment(filename):
    attachment = KnowledgeAttachment.query.filter_by(stored_filename=filename).first_or_404()
    article = KnowledgeArticle.query.get_or_404(attachment.article_id)
    if not article.is_published and not _require_editor():
        flash(_("You do not have access to this attachment."), "warning")
        return redirect(url_for('knowledge.view_article', article_id=article.id))
    upload_folder = _ensure_upload_folder()
    return send_from_directory(upload_folder, filename, as_attachment=True)


@knowledge_bp.route("/article/<int:article_id>/version/<int:version_id>")
@login_required
def view_version(article_id, version_id):
    if not _require_editor():
        flash(_("You do not have permission to view historical versions."), "warning")
        return redirect(url_for("knowledge.view_article", article_id=article_id))

    article = KnowledgeArticle.query.get_or_404(article_id)
    version = KnowledgeArticleVersion.query.filter_by(id=version_id, article_id=article_id).first_or_404()
    return render_template(
        "knowledge/version.html",
        article=article,
        version=version,
    )
