import os
import time
import shutil
from flask import Blueprint, render_template, request, jsonify, abort, current_app
from flask_login import login_required, current_user
from app.utils.files import secure_filename
from app import db, csrf
from app.models.user import User
from app.models.ticket import Ticket
from app.models.knowledge import KnowledgeArticle, KnowledgeArticleVersion, KnowledgeAttachment
from app.models.inventory import SoftwareAsset, HardwareAsset
from app.models.contracts import Contract
from app.models.api import ApiClient
from app.models.email_ingest import EmailIngestConfig
from app.models.menu import MenuPermission
from app.models.backup import TapeLocation, TapeCustodyEvent, BackupAuditLog
from app.models.collab import (
    ChatConversation,
    ChatMembership,
    ChatMessage,
    ChatMessageRead,
    ChatFavorite,
)
from app.models.assistant import AssistantSession, AssistantDocument
from app.utils.roles import role_required
from app.utils.security import validate_password_strength
from sqlalchemy import func, or_, text, inspect
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

users_bp = Blueprint("users", __name__)

ALLOWED_AVATAR_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_AVATAR_SIZE = 5 * 1024 * 1024  # 5MB


def _checkbox_enabled(form, name: str) -> bool:
    """
    Interpret checkbox inputs that include a hidden fallback value.
    The hidden input usually precedes the checkbox, so we use the last value.
    """
    values = form.getlist(name)
    if not values:
        return False
    value = values[-1]
    if isinstance(value, str):
        value = value.lower()
    return value in {"1", "true", "on", "yes"}


@users_bp.route("/users", methods=["GET"])
@login_required
@role_required('admin', 'manager')
def list_users():
    users = User.query.order_by(User.id.desc()).all()
    total_users = len(users)
    active_users = sum(1 for user in users if user.active)
    inactive_users = total_users - active_users
    role_breakdown = {role: sum(1 for user in users if (user.role or "").lower() == role) for role in ['admin', 'manager', 'technician', 'user']}
    return render_template(
        "users/list.html",
        users=users,
        total_users=total_users,
        active_users=active_users,
        inactive_users=inactive_users,
        role_breakdown=role_breakdown,
    )


@csrf.exempt
@users_bp.route("/users/add", methods=["POST"])
@login_required
@role_required('admin')
def add_user():
    username = (request.form.get("username") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    full_name = (request.form.get("full_name") or "").strip()
    password = request.form.get("password") or ""
    password_confirm = request.form.get("password_confirm") or ""
    role = request.form.get("role", "user")
    department = request.form.get("department", "")
    active_values = request.form.getlist("active")
    active_value = active_values[-1] if active_values else "1"
    notify_email = _checkbox_enabled(request.form, "notify_team_ticket_email")
    notify_teams = _checkbox_enabled(request.form, "notify_team_ticket_teams")
    teams_webhook_url = (request.form.get("teams_webhook_url") or "").strip()

    if not username or not email or not password:
        return jsonify(success=False, message="Missing required fields"), 400

    if password != password_confirm:
        return jsonify(success=False, message="Passwords do not match"), 400

    if User.query.filter((func.lower(User.username) == username.lower()) | (func.lower(User.email) == email.lower())).first():
        return jsonify(success=False, message="User already exists"), 400

    ok, messages = validate_password_strength(password)
    if not ok:
        return jsonify(success=False, message=" ".join(messages)), 400

    if role != "manager":
        notify_email = False
        notify_teams = False
        teams_webhook_url = ""
    elif notify_teams and not teams_webhook_url:
        return jsonify(success=False, message="Provide a Teams webhook URL or disable Teams notifications."), 400

    user = User(
        username=username,
        email=email,
        full_name=full_name or None,
        role=role,
        department=department,
        active=active_value in {"1", "true", "on", "yes"},
        notify_team_ticket_email=notify_email,
        notify_team_ticket_teams=notify_teams,
        teams_webhook_url=teams_webhook_url or None,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return jsonify(success=True, message="User created successfully")


@csrf.exempt
@users_bp.route("/users/<int:id>/edit", methods=["POST"])
@login_required
@role_required('admin', 'manager')
def edit_user(id):
    user = User.query.get_or_404(id)
    if current_user.role != 'admin' and current_user.id != id:
        abort(403)

    new_username = request.form.get("username", "").strip()
    new_email = request.form.get("email", "").strip()
    new_full_name = request.form.get("full_name", user.full_name or "").strip()
    new_role = request.form.get("role", user.role)
    new_department = request.form.get("department", user.department)
    new_password = request.form.get("password", "").strip()
    new_password_confirm = request.form.get("password_confirm", "").strip()
    active_values = request.form.getlist("active")
    active_value = active_values[-1] if active_values else ("1" if user.active else "0")
    notify_email = _checkbox_enabled(request.form, "notify_team_ticket_email")
    notify_teams = _checkbox_enabled(request.form, "notify_team_ticket_teams")
    teams_webhook_url = (request.form.get("teams_webhook_url") or "").strip()

    if not new_username or not new_email:
        return jsonify(success=False, message="Username and email are required"), 400

    # Prevent duplicate usernames
    if User.query.filter(func.lower(User.username) == new_username.lower(), User.id != id).first():
        return jsonify(success=False, message=f"Username '{new_username}' already exists"), 400

    if User.query.filter(func.lower(User.email) == new_email.lower(), User.id != id).first():
        return jsonify(success=False, message=f"Email '{new_email}' already exists"), 400

    user.username = new_username
    user.email = new_email
    user.full_name = new_full_name or None
    user.role = new_role
    user.department = new_department
    user.active = active_value in {"1", "true", "on", "yes"}
    if user.role != "manager":
        user.notify_team_ticket_email = False
        user.notify_team_ticket_teams = False
        user.teams_webhook_url = None
    else:
        if notify_teams and not teams_webhook_url:
            return jsonify(success=False, message="Provide a Teams webhook URL or disable Teams notifications."), 400
        user.notify_team_ticket_email = notify_email
        user.notify_team_ticket_teams = notify_teams
        user.teams_webhook_url = teams_webhook_url or None
    if new_password:
        if new_password != new_password_confirm:
            return jsonify(success=False, message="Passwords do not match"), 400
        ok, messages = validate_password_strength(new_password)
        if not ok:
            return jsonify(success=False, message=" ".join(messages)), 400
        user.set_password(new_password)

    db.session.commit()
    return jsonify(success=True, message="User updated successfully")


def _allowed_avatar(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_AVATAR_EXTENSIONS


def _avatar_upload_folder() -> str:
    folder = current_app.config.get("AVATAR_UPLOAD_FOLDER")
    if not folder:
        folder = os.path.join(current_app.static_folder, "uploads", "avatars")
    os.makedirs(folder, exist_ok=True)
    return folder


def _legacy_avatar_folder() -> str:
    return os.path.join(current_app.root_path, "static", "uploads", "avatars")


def _remove_avatar_file(filename: str) -> None:
    if not filename:
        return
    paths = [os.path.join(_avatar_upload_folder(), filename),
             os.path.join(_legacy_avatar_folder(), filename)]
    for path in paths:
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            current_app.logger.warning("Failed to remove avatar file %s", path, exc_info=True)


@users_bp.route("/profile", methods=["POST"])
@login_required
def update_profile():
    user = current_user
    full_name = (request.form.get("full_name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()

    if not email:
        return jsonify(success=False, message="Email is required."), 400

    duplicate_email = (
        User.query.filter(func.lower(User.email) == email.lower(), User.id != user.id).first()
    )
    if duplicate_email:
        return jsonify(success=False, message="Another account already uses that email address."), 400

    notify_email = _checkbox_enabled(request.form, "notify_team_ticket_email")
    notify_teams = _checkbox_enabled(request.form, "notify_team_ticket_teams")
    teams_webhook_url = (request.form.get("teams_webhook_url") or "").strip()

    use_gravatar = bool(request.form.get("use_gravatar"))
    use_profile_picture = bool(request.form.get("use_profile_picture"))
    remove_avatar = bool(request.form.get("remove_avatar"))

    avatar_file = request.files.get("profile_image")

    if use_profile_picture:
        if avatar_file and avatar_file.filename:
            if not _allowed_avatar(avatar_file.filename):
                return jsonify(
                    success=False,
                    message="Invalid image type. Please upload PNG, JPG, JPEG, GIF or WEBP.",
                ), 400
            try:
                avatar_file.stream.seek(0, os.SEEK_END)
                size = avatar_file.stream.tell()
                avatar_file.stream.seek(0)
            except OSError:
                size = 0
            if size and size > MAX_AVATAR_SIZE:
                return jsonify(success=False, message="Profile image must be smaller than 5MB."), 400
            filename_root = f"user_{user.id}_{int(time.time())}"
            extension = avatar_file.filename.rsplit(".", 1)[1].lower()
            filename = secure_filename(f"{filename_root}.{extension}", allow_unicode=True)
            upload_folder = _avatar_upload_folder()
            upload_path = os.path.join(upload_folder, filename)
            avatar_file.save(upload_path)
            if user.avatar_filename and user.avatar_filename != filename:
                _remove_avatar_file(user.avatar_filename)
            user.avatar_filename = filename
        elif not user.avatar_filename:
            return jsonify(
                success=False,
                message="Upload a profile image or disable the custom picture option.",
            ), 400
        user.use_gravatar = False
    elif use_gravatar:
        user.use_gravatar = True
    else:
        user.use_gravatar = False
        if remove_avatar and user.avatar_filename:
            _remove_avatar_file(user.avatar_filename)
            user.avatar_filename = None

    if user.role == "manager":
        if notify_teams and not teams_webhook_url:
            return jsonify(success=False, message="Provide a Teams webhook URL or disable Teams notifications."), 400
        user.notify_team_ticket_email = notify_email
        user.notify_team_ticket_teams = notify_teams
        user.teams_webhook_url = teams_webhook_url or None
    else:
        user.notify_team_ticket_email = False
        user.notify_team_ticket_teams = False
        user.teams_webhook_url = None

    user.full_name = full_name or None
    user.email = email

    if user.avatar_filename:
        new_path = os.path.join(_avatar_upload_folder(), user.avatar_filename)
        legacy_path = os.path.join(_legacy_avatar_folder(), user.avatar_filename)
        if not os.path.isfile(new_path) and os.path.isfile(legacy_path):
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            try:
                shutil.move(legacy_path, new_path)
            except OSError:
                current_app.logger.warning("Failed to migrate legacy avatar %s", legacy_path, exc_info=True)

    new_password = request.form.get("new_password") or ""
    confirm_password = request.form.get("confirm_password") or ""
    current_password = request.form.get("current_password") or ""

    if new_password or confirm_password or current_password:
        if not current_password:
            return jsonify(success=False, message="Provide your current password to set a new one."), 400
        if not user.check_password(current_password):
            return jsonify(success=False, message="Current password is incorrect."), 400
        if new_password != confirm_password:
            return jsonify(success=False, message="New passwords do not match."), 400
        ok, messages = validate_password_strength(new_password)
        if not ok:
            return jsonify(success=False, message=" ".join(messages)), 400
        user.set_password(new_password)

    db.session.add(user)
    db.session.commit()

    return jsonify(
        success=True,
        message="Profile updated successfully.",
        avatar_url=user.avatar_url(64),
        display_name=user.display_name,
        handle=f"@{user.username}",
        email=user.email,
    )


def _cleanup_user_relationships(target: User, acting: User) -> None:
    """
    Prepare related records so that deleting `target` will not violate FK constraints.
    Reassign ownership metadata to the acting admin when possible and nullify optional links.
    """

    acting_id = acting.id if acting and isinstance(acting.id, int) else None
    user_id = target.id

    if acting_id == user_id:
        # Should never happen because we disallow self-deletion,
        # but guard to avoid rewriting ownership to the same record.
        acting_id = None

    # Assistant sessions and related documents/messages
    AssistantDocument.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    AssistantSession.query.filter_by(user_id=user_id).delete(synchronize_session=False)

    # Tickets
    Ticket.query.filter_by(assigned_to=user_id).update(
        {Ticket.assigned_to: None}, synchronize_session=False
    )
    if acting_id:
        Ticket.query.filter_by(created_by=user_id).update(
            {Ticket.created_by: acting_id}, synchronize_session=False
        )

    # Knowledge base
    if acting_id:
        KnowledgeArticle.query.filter_by(created_by=user_id).update(
            {KnowledgeArticle.created_by: acting_id}, synchronize_session=False
        )
        KnowledgeArticle.query.filter_by(updated_by=user_id).update(
            {KnowledgeArticle.updated_by: acting_id}, synchronize_session=False
        )
        KnowledgeArticleVersion.query.filter_by(created_by=user_id).update(
            {KnowledgeArticleVersion.created_by: acting_id}, synchronize_session=False
        )
    KnowledgeAttachment.query.filter_by(uploaded_by=user_id).update(
        {KnowledgeAttachment.uploaded_by: None}, synchronize_session=False
    )

    # Inventory assets
    SoftwareAsset.query.filter_by(assigned_to=user_id).update(
        {SoftwareAsset.assigned_to: None}, synchronize_session=False
    )
    HardwareAsset.query.filter_by(assigned_to=user_id).update(
        {HardwareAsset.assigned_to: None}, synchronize_session=False
    )

    # Contracts
    Contract.query.filter_by(owner_id=user_id).update(
        {Contract.owner_id: None}, synchronize_session=False
    )

    # API clients
    ApiClient.query.filter_by(default_user_id=user_id).update(
        {"default_user_id": acting_id}, synchronize_session=False
    )

    # Email ingest configurations
    updates = {}
    updates_assign = {}
    if acting_id:
        updates["created_by_user_id"] = acting_id
    updates_assign["assign_to_user_id"] = None
    if updates:
        EmailIngestConfig.query.filter_by(created_by_user_id=user_id).update(
            updates, synchronize_session=False
        )
    EmailIngestConfig.query.filter_by(assign_to_user_id=user_id).update(
        updates_assign, synchronize_session=False
    )

    # Menu permissions
    MenuPermission.query.filter_by(user_id=user_id).delete(synchronize_session=False)

    # Backup module
    replacement = acting_id if acting_id else None
    TapeLocation.query.filter_by(created_by_user_id=user_id).update(
        {"created_by_user_id": replacement}, synchronize_session=False
    )
    TapeCustodyEvent.query.filter_by(created_by_user_id=user_id).update(
        {"created_by_user_id": replacement}, synchronize_session=False
    )
    BackupAuditLog.query.filter_by(changed_by_user_id=user_id).update(
        {"changed_by_user_id": replacement}, synchronize_session=False
    )

    # Collaboration / chat
    ChatMessageRead.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    ChatMembership.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    ChatFavorite.query.filter(
        or_(ChatFavorite.user_id == user_id, ChatFavorite.favorite_user_id == user_id)
    ).delete(synchronize_session=False)

    ChatMessage.query.filter_by(sender_id=user_id).delete(synchronize_session=False)
    ChatConversation.query.filter_by(created_by=user_id).update(
        {"created_by": acting_id}, synchronize_session=False
    )

    # Backup jobs (raw table not mapped)
    replacement = acting_id if acting_id is not None else None
    bind = db.session.get_bind()
    if bind is not None:
        inspector = inspect(bind)
        if inspector.has_table("backup_job"):
            if replacement is not None:
                db.session.execute(
                    text(
                        "UPDATE backup_job SET responsible_user_id = :replacement WHERE responsible_user_id = :uid"
                    ),
                    {"replacement": replacement, "uid": user_id},
                )
            else:
                db.session.execute(
                    text(
                        "UPDATE backup_job SET responsible_user_id = NULL WHERE responsible_user_id = :uid"
                    ),
                    {"uid": user_id},
                )

    # Flush to ensure pending deletes/updates reflected before actual delete
    db.session.flush()


@csrf.exempt
@users_bp.route("/users/<int:id>/delete", methods=["POST"])
@login_required
@role_required('admin')
def delete_user(id):
    if current_user.id == id:
        return jsonify(success=False, message="You cannot delete your own account"), 400
    user = User.query.get_or_404(id)
    _cleanup_user_relationships(user, current_user)
    try:
        db.session.delete(user)
        db.session.commit()
        return jsonify(success=True, message="User deleted successfully.")
    except IntegrityError as exc:
        db.session.rollback()
        current_app.logger.exception("Integrity error while deleting user %s", id)
        return jsonify(
            success=False,
            message=(
                "Cannot delete this user because related records still reference them. "
                "Consider deactivating the account instead."
            ),
        ), 400
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Failed to delete user %s", id)
        return jsonify(success=False, message="Failed to delete user due to a server error."), 500
