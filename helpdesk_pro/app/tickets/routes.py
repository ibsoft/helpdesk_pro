from __future__ import annotations

from sqlalchemy import or_, func
import copy
import os
import uuid
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

import requests

from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, abort, current_app, send_from_directory, send_file
from flask_login import login_required, current_user
from flask_babel import gettext as _
from app.utils.files import secure_filename
from flask_mail import Message

from app import db, csrf
from app.models.ticket import Ticket, TicketComment, Attachment, AuditLog, TicketArchive
from app.models.user import User
from app.mail_utils import queue_mail_with_optional_auth
from app.background import submit_background_task
from app.tickets.archive_utils import build_archive_from_ticket

tickets_bp = Blueprint("tickets", __name__)


def _ensure_ticket_upload_folder():
    """Ensure instance-level tickets upload folder exists and return its path."""
    upload_folder = current_app.config.get("TICKETS_UPLOAD_FOLDER")
    if not upload_folder:
        upload_folder = os.path.join(current_app.instance_path, "tickets_uploads")
        current_app.config["TICKETS_UPLOAD_FOLDER"] = upload_folder
    os.makedirs(upload_folder, exist_ok=True)
    return upload_folder

LOCAL_TZ = ZoneInfo("Europe/Athens")


def to_local(dt):
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(LOCAL_TZ)


def _shorten(text, length=200):
    if not text:
        return ""
    text = text.strip()
    if len(text) <= length:
        return text
    return text[: max(0, length - 3)] + "..."


def _user_can_archive_ticket(ticket: Ticket) -> bool:
    if current_user.role == "admin":
        return True
    return ticket.created_by == current_user.id or ticket.assigned_to == current_user.id


def _can_view_archive(archive: TicketArchive) -> bool:
    if current_user.role == "admin":
        return True
    allowed = (
        archive.created_by == current_user.id
        or archive.assigned_to == current_user.id
        or archive.archived_by == current_user.id
    )
    if current_user.role == "manager":
        dept_value = current_user.department
        dept_ids = {u.id for u in User.query.filter_by(department=dept_value).all()}
        if archive.created_by in dept_ids or archive.assigned_to in dept_ids:
            allowed = True
    return allowed


def _archive_detail_redirect(source: Optional[str], archive: TicketArchive):
    target = (source or "").lower()
    if target == "manage":
        try:
            return redirect(url_for("manage.ticket_archive_detail", archive_id=archive.id))
        except Exception:
            pass
    if request.referrer:
        return redirect(request.referrer)
    return redirect(url_for("tickets.view_ticket_archive", archive_id=archive.id))


def _ticket_url(ticket):
    try:
        path = url_for("tickets.view_ticket", id=ticket.id)
    except RuntimeError:
        path = f"/tickets/{ticket.id}/view"

    base_url = (current_app.config.get("BASE_URL") or "").rstrip("/")
    if base_url:
        return f"{base_url}{path}"
    try:
        return url_for("tickets.view_ticket", id=ticket.id, _external=True)
    except RuntimeError:
        return path


def _notify_team_managers(ticket, actor, event_summary, details=None):
    """
    Notify managers in the actor's department when a team member updates a ticket.
    """

    if not actor or actor.role not in {"user", "technician", "manager"}:
        return
    department = (actor.department or "").strip()
    if not department:
        return

    managers = (
        User.query.filter(
        User.role == "manager",
        User.active.is_(True),
        func.lower(User.department) == department.lower(),
        or_(User.notify_team_ticket_email.is_(True), User.notify_team_ticket_teams.is_(True)),
    ).all()
    )
    if not managers:
        return

    ticket_link = _ticket_url(ticket)
    subject = f"[Ticket #{ticket.id}] {ticket.subject or 'Ticket'} – {event_summary}"
    body_lines = [
        f"Ticket #{ticket.id}: {ticket.subject or 'No subject'}",
        f"Event: {event_summary}",
        f"Actor: {actor.display_name} ({actor.username})",
        f"Department: {department}",
        f"Status: {ticket.status or 'Unknown'} | Priority: {ticket.priority or 'Unspecified'}",
    ]
    if details:
        body_lines.append("")
        body_lines.append(details)
    body_lines.append("")
    body_lines.append(f"View ticket: {ticket_link}")
    body = "\n".join(body_lines)

    teams_text = (
        f"**{subject}**\n\n"
        f"Ticket #{ticket.id}: {ticket.subject or 'No subject'}\n"
        f"Event: {event_summary}\n"
        f"Actor: {actor.display_name} ({actor.username})\n"
        f"Department: {department}\n"
        f"Status: {ticket.status or 'Unknown'} | Priority: {ticket.priority or 'Unspecified'}\n"
    )
    if details:
        teams_text += f"\n{details}\n"
    teams_text += f"\n[View ticket]({ticket_link})"

    actor_line = f"{actor.display_name} ({actor.username})"
    teams_facts = [
        {"name": "Ticket", "value": f"#{ticket.id}: {ticket.subject or 'No subject'}"},
        {"name": "Department", "value": department},
        {"name": "Status", "value": ticket.status or 'Unknown'},
        {"name": "Priority", "value": ticket.priority or 'Unspecified'},
    ]
    teams_payload = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": subject,
        "themeColor": "4B5FC1",
        "title": subject,
        "text": teams_text,
        "sections": [
            {
                "activityTitle": actor_line,
                "activityImage": actor.avatar_url(64) if hasattr(actor, "avatar_url") else None,
                "activitySubtitle": event_summary,
                "facts": teams_facts,
                "markdown": True,
                **({"text": details} if details else {}),
            }
        ],
        "potentialAction": [
            {
                "@type": "OpenUri",
                "name": "View ticket",
                "targets": [
                    {
                        "os": "default",
                        "uri": ticket_link,
                    }
                ],
            }
        ],
    }
    if not teams_payload["sections"][0]["activityImage"]:
        teams_payload["sections"][0].pop("activityImage")
    teams_payload["summary"] = actor.display_name

    mail_sender = current_app.config.get("MAIL_DEFAULT_SENDER") or current_app.config.get("MAIL_USERNAME")
    warned_mail = False

    for manager in managers:
        manager_email = (manager.email or "").strip() if manager.email else None
        manager_username = manager.username
        teams_webhook = manager.teams_webhook_url

        if manager.notify_team_ticket_email:
            if mail_sender and manager_email:
                message = Message(subject=subject, recipients=[manager_email], body=body, sender=mail_sender)
                queue_mail_with_optional_auth(
                    message,
                    description=f"ticket notification email to {manager_email}",
                )
            elif not mail_sender and not warned_mail:
                current_app.logger.warning("MAIL_DEFAULT_SENDER is not configured; skipping ticket notification emails.")
                warned_mail = True

        if manager.notify_team_ticket_teams and teams_webhook:
            payload = copy.deepcopy(teams_payload)

            def _send_teams_notification(
                webhook_url=teams_webhook,
                username=manager_username,
                data=payload,
            ):
                try:
                    response = requests.post(webhook_url, json=data, timeout=6)
                    if response.status_code >= 400:
                        current_app.logger.warning(
                            "Teams webhook for manager %s returned status %s", username, response.status_code
                        )
                except requests.RequestException:
                    current_app.logger.exception(
                        "Failed to send Teams ticket notification for manager %s", username
                    )

            submit_background_task(
                _send_teams_notification,
                description=f"Teams ticket notification for manager {manager_username}",
            )


# ============================================================
# LIST
# ============================================================
@tickets_bp.route("/tickets")
@login_required
def list_tickets():
    """Admin sees all, Manager sees department + own, User sees own."""
    try:
        if current_user.role == "admin":
            tickets = Ticket.query.order_by(Ticket.id.desc()).all()
            users = User.query.filter_by(
                active=True).order_by(User.username).all()

        elif current_user.role == "manager":
            dept_users = User.query.filter_by(
                department=current_user.department
            ).with_entities(User.id).subquery()

            tickets = Ticket.query.filter(
                or_(
                    Ticket.created_by == current_user.id,
                    Ticket.assigned_to == current_user.id,
                    Ticket.created_by.in_(dept_users),
                    Ticket.assigned_to.in_(dept_users)
                )
            ).order_by(Ticket.id.desc()).all()

            allowed_roles = ["technician", "user"]
            users = User.query.filter(
                User.active.is_(True),
                User.department == current_user.department,
                User.role.in_(allowed_roles),
            ).order_by(User.username).all()

            if current_user.active and not any(u.id == current_user.id for u in users):
                users.append(current_user)
                users.sort(key=lambda u: (u.username or "").lower())

        else:
            tickets = Ticket.query.filter(
                or_(Ticket.created_by == current_user.id,
                    Ticket.assigned_to == current_user.id)
            ).order_by(Ticket.id.desc()).all()
            users = []

        return render_template("tickets/list.html", tickets=tickets, users=users)
    except Exception as e:
        flash(f"Error loading tickets: {str(e)}", "danger")
        return redirect(url_for("dashboard.index"))


# ============================================================
# CREATE
# ============================================================
@tickets_bp.route("/tickets/add", methods=["POST"])
@login_required
def create_ticket():
    try:
        subject = request.form.get("subject")
        description = request.form.get("description")

        if not subject or not description:
            msg = "Subject and description are required."
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify(success=False, message=msg, category="warning"), 400
            flash(msg, "warning")
            return redirect(url_for("tickets.list_tickets"))

        t = Ticket(
            subject=subject,
            description=description,
            priority=request.form.get("priority"),
            status="Open",
            created_by=current_user.id,
            department=current_user.department
        )
        db.session.add(t)
        db.session.commit()

        db.session.add(AuditLog(
            action="Create Ticket",
            username=current_user.username,
            ticket_id=t.id
        ))
        db.session.commit()

        _notify_team_managers(
            t,
            current_user,
            "created a ticket",
            f"Priority: {t.priority or 'Unspecified'} | Status: {t.status or 'Open'}",
        )

        msg = f"Ticket #{t.id} created successfully."
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            # Return simple success response - let frontend handle page reload
            return jsonify(success=True, message=msg, category="success")

        flash(msg, "success")
        return redirect(url_for("tickets.list_tickets"))

    except Exception as e:
        msg = f"Error creating ticket: {str(e)}"
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify(success=False, message=msg, category="danger"), 500
        flash(msg, "danger")
        return redirect(url_for("tickets.list_tickets"))


# ============================================================
# EDIT
# ============================================================
@tickets_bp.route("/tickets/<int:id>/edit", methods=["GET", "POST"])
@login_required
def edit_ticket(id):
    """Manager can assign only within department; Admin to all."""
    ticket = Ticket.query.get_or_404(id)
    old_status = ticket.status

    try:
        if current_user.role == "admin":
            users = User.query.filter_by(active=True).order_by(User.username).all()
        elif current_user.role == "manager":
            allowed_roles = ["technician", "user"]
            users = User.query.filter(
                User.active.is_(True),
                User.department == current_user.department,
                User.role.in_(allowed_roles),
            ).order_by(User.username).all()
            if current_user.active and not any(u.id == current_user.id for u in users):
                users.append(current_user)
                users.sort(key=lambda u: (u.username or "").lower())
        else:
            users = []

        if request.method == "POST":
            original_state = {
                "subject": ticket.subject,
                "description": ticket.description,
                "priority": ticket.priority,
                "status": ticket.status,
                "assigned_to": ticket.assigned_to,
            }

            ticket.subject = request.form.get("subject", ticket.subject)
            ticket.description = request.form.get("description", ticket.description)
            ticket.priority = request.form.get("priority", ticket.priority)
            ticket.status = request.form.get("status", ticket.status)
            assigned_to_val = request.form.get("assigned_to")

            if current_user.role == "manager" and assigned_to_val:
                assigned_user = User.query.get(int(assigned_to_val))
                if not assigned_user:
                    msg = "Selected user was not found."
                    return jsonify(success=False, message=msg, category="danger")
                if assigned_user.id != current_user.id:
                    allowed_roles = {"technician", "user"}
                    if assigned_user.department != current_user.department:
                        msg = "Managers can assign only to members of their team."
                        return jsonify(success=False, message=msg, category="danger")
                    if assigned_user.role not in allowed_roles:
                        msg = "Managers can assign only to Technicians or Users from their team."
                        return jsonify(success=False, message=msg, category="danger")
                if not assigned_user.active:
                    msg = "Cannot assign tickets to inactive users."
                    # Always return JSON for modal consistency
                    return jsonify(success=False, message=msg, category="danger")

            if current_user.role in ["admin", "manager"]:
                ticket.assigned_to = int(
                    assigned_to_val) if assigned_to_val and assigned_to_val.isdigit() else None

            if ticket.status == "Closed" and old_status != "Closed":
                ticket.closed_at = datetime.utcnow()
            elif old_status == "Closed" and ticket.status != "Closed":
                ticket.closed_at = None

            db.session.add(AuditLog(action="Edit Ticket",
                           username=current_user.username, ticket_id=ticket.id))
            db.session.commit()

            changes = []
            if ticket.subject != original_state["subject"]:
                changes.append("Subject updated.")
            if ticket.description != original_state["description"]:
                changes.append("Description updated.")
            if ticket.priority != original_state["priority"]:
                changes.append(
                    f"Priority: {original_state['priority'] or 'Unspecified'} → {ticket.priority or 'Unspecified'}"
                )
            if ticket.status != original_state["status"]:
                changes.append(
                    f"Status: {original_state['status'] or 'Unspecified'} → {ticket.status or 'Unspecified'}"
                )
            if ticket.assigned_to != original_state["assigned_to"]:
                old_assignee = None
                new_assignee = None
                if original_state["assigned_to"]:
                    old_user = User.query.get(original_state["assigned_to"])
                    old_assignee = old_user.display_name if old_user else f"User {original_state['assigned_to']}"
                if ticket.assigned_to:
                    new_user = User.query.get(ticket.assigned_to)
                    new_assignee = new_user.display_name if new_user else f"User {ticket.assigned_to}"
                changes.append(
                    f"Assignee: {old_assignee or 'Unassigned'} → {new_assignee or 'Unassigned'}"
                )

            details = "\n".join(changes) if changes else "Ticket details were updated."
            _notify_team_managers(ticket, current_user, "updated a ticket", details)

            return jsonify(success=True, message=f"Ticket #{ticket.id} updated successfully.", category="success")

        # --- GET ---
        # For AJAX requests, return only the form content
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.args.get('ajax'):
            return render_template("tickets/edit.html", ticket=ticket, users=users)
        
        # For regular requests (fallback)
        class DummyForm:
            def __init__(self, t):
                self.subject = type('F', (), {'data': t.subject})()
                self.description = type('F', (), {'data': t.description})()
                self.priority = type('F', (), {'data': t.priority})()
                self.status = type('F', (), {'data': t.status})()
                self.department = type('F', (), {'data': t.department})()
                self.assigned_to = type('F', (), {'data': t.assigned_to})()

        form = DummyForm(ticket)
        return render_template("tickets/edit.html", form=form, users=users, mode="edit", ticket=ticket)

    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=f"Error editing ticket: {str(e)}", category="danger")

# ============================================================
# VIEW
# ============================================================
@tickets_bp.route("/tickets/<int:id>/view", methods=["GET"])
@login_required
def view_ticket(id):
    t = Ticket.query.get_or_404(id)

    try:
        allowed = False
        if current_user.role == "admin":
            allowed = True
        elif current_user.role == "manager":
            dept_user_ids = {u.id for u in User.query.filter_by(
                department=current_user.department).all()}
            if (
                t.created_by == current_user.id
                or t.assigned_to == current_user.id
                or (t.created_by in dept_user_ids)
                or (t.assigned_to in dept_user_ids)
            ):
                allowed = True
        else:
            if t.created_by == current_user.id or t.assigned_to == current_user.id:
                allowed = True

        if not allowed:
            flash("You are not authorized to view this ticket.", "danger")
            abort(403)

        comments = TicketComment.query.filter_by(
            ticket_id=id).order_by(TicketComment.created_at.asc()).all()
        attachments = Attachment.query.filter_by(
            ticket_id=id).order_by(Attachment.uploaded_at.desc()).all()
        logs = AuditLog.query.filter_by(ticket_id=id).order_by(
            AuditLog.timestamp.desc()).all()

        comments_data = [{
            "user": c.user,
            "comment": c.comment,
            "created_at_local": to_local(c.created_at)
        } for c in comments]

        attachments_data = [{
            "filename": a.filename,
            "filepath": a.filepath,
            "uploaded_by": a.uploaded_by,
            "uploaded_at_local": to_local(a.uploaded_at)
        } for a in attachments]

        logs_data = [{
            "action": l.action,
            "username": l.username,
            "timestamp_local": to_local(l.timestamp)
        } for l in logs]

        is_modal_request = request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.args.get("modal")
        template_name = "tickets/view.html" if is_modal_request else "tickets/view_page.html"

        return render_template(
            template_name,
            ticket=t,
            comments=comments_data,
            attachments=attachments_data,
            logs=logs_data,
        )
    except Exception as e:
        flash(f"Error viewing ticket: {str(e)}", "danger")
        return redirect(url_for("tickets.list_tickets"))


# ============================================================
# COMMENT
# ============================================================
@tickets_bp.route("/tickets/<int:id>/comment", methods=["POST"])
@login_required
def add_comment(id):
    t = Ticket.query.get_or_404(id)
    text = request.form.get("comment")
    if not text:
        flash("Cannot add an empty comment.", "warning")
        return jsonify(error="Empty comment"), 400

    try:
        allowed = False
        if current_user.role == "admin":
            allowed = True
        elif current_user.role == "manager":
            dept_user_ids = {u.id for u in User.query.filter_by(
                department=current_user.department).all()}
            if (
                t.created_by == current_user.id
                or t.assigned_to == current_user.id
                or (t.created_by in dept_user_ids)
                or (t.assigned_to in dept_user_ids)
            ):
                allowed = True
        else:
            if t.created_by == current_user.id or t.assigned_to == current_user.id:
                allowed = True

        if not allowed:
            flash("Not authorized to comment on this ticket.", "danger")
            abort(403)

        c = TicketComment(
            ticket_id=id, user=current_user.username, comment=text)
        db.session.add(c)
        db.session.add(AuditLog(action="Add Comment",
                                username=current_user.username, ticket_id=id))
        db.session.commit()

        _notify_team_managers(t, current_user, "commented on a ticket", f"Comment: {_shorten(text, 240)}")

        flash("Comment added successfully.", "success")
        return jsonify(success=True)
    except Exception as e:
        flash(f"Error adding comment: {str(e)}", "danger")
        return jsonify(error=str(e)), 500


# ============================================================
# UPLOAD
# ============================================================
@tickets_bp.route("/tickets/<int:id>/upload", methods=["POST"])
@login_required
def upload_file(id):
    t = Ticket.query.get_or_404(id)
    f = request.files.get("file")
    if not f or f.filename == "":
        flash("No file selected for upload.", "warning")
        return jsonify(error="No file"), 400

    try:
        dept_user_ids = {u.id for u in User.query.filter_by(
            department=current_user.department).all()}
        allowed = (
            current_user.role == "admin"
            or (current_user.role == "manager" and (
                t.created_by == current_user.id
                or t.assigned_to == current_user.id
                or (t.created_by in dept_user_ids)
                or (t.assigned_to in dept_user_ids)
            ))
            or (t.created_by == current_user.id or t.assigned_to == current_user.id)
        )

        if not allowed:
            flash("You are not authorized to upload to this ticket.", "danger")
            abort(403)

        upload_folder = _ensure_ticket_upload_folder()

        original_name = (f.filename or "").strip()
        safe_name = secure_filename(original_name, allow_unicode=True)
        if not safe_name:
            base, ext = os.path.splitext(original_name)
            fallback = (base or "attachment").strip().replace(" ", "_")
            safe_name = secure_filename(f"{fallback}{ext}", allow_unicode=True) or "attachment"

        # Prefix with UUID to avoid collisions and keep URL-safe length
        unique_prefix = uuid.uuid4().hex
        max_safe_length = max(1, 255 - len(unique_prefix) - 1)
        if len(safe_name) > max_safe_length:
            base, safe_ext = os.path.splitext(safe_name)
            allowed = max_safe_length - len(safe_ext)
            safe_name = (f"{base[:max(0, allowed)]}{safe_ext}" if allowed > 0 else safe_name[:max_safe_length])
        safe_name = (safe_name[:max_safe_length] or "attachment").strip(".")
        stored_name = f"{unique_prefix}_{safe_name}"

        stored_path = os.path.join(upload_folder, stored_name)
        f.save(stored_path)

        # Public web path is now a protected route
        web_path = f"/tickets/attachments/{stored_name}"

        display_name = original_name or safe_name

        a = Attachment(
            ticket_id=id,
            filename=display_name,
            filepath=web_path,
            uploaded_by=current_user.username,
        )
        db.session.add(a)
        db.session.add(AuditLog(action="Upload File",
                                username=current_user.username, ticket_id=id))
        db.session.commit()

        _notify_team_managers(t, current_user, "added an attachment", f"Attachment: {display_name}")

        flash(f"File '{display_name}' uploaded successfully.", "success")
        return jsonify(success=True)
    except Exception as e:
        flash(f"Error uploading file: {str(e)}", "danger")
        return jsonify(error=str(e)), 500


# ============================================================
# DELETE
# ============================================================
@tickets_bp.route("/tickets/<int:id>/delete", methods=["POST"])
@login_required
def delete_ticket(id):
    try:
        t = Ticket.query.get_or_404(id)
        # Remove attachment files from disk before deleting DB records
        try:
            upload_folder = _ensure_ticket_upload_folder()
            static_upload_dir = os.path.join(
                os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")),
                "static",
                "uploads",
            )
            for a in list(t.attachments or []):
                path_val = a.filepath or ""
                # Instance-stored files (new behavior)
                stored_name = os.path.basename(path_val)
                if path_val.startswith("/tickets/attachments/") and stored_name:
                    file_path = os.path.join(upload_folder, stored_name)
                    if os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                        except OSError:
                            pass
                # Legacy static files cleanup (best-effort)
                elif path_val.startswith("/static/uploads/"):
                    legacy_name = os.path.basename(path_val)
                    legacy_path = os.path.join(static_upload_dir, legacy_name)
                    if os.path.exists(legacy_path):
                        try:
                            os.remove(legacy_path)
                        except OSError:
                            pass
        except Exception:
            # Continue with DB deletion even if file cleanup fails
            pass
        db.session.delete(t)
        db.session.add(AuditLog(action="Delete Ticket",
                                username=current_user.username, ticket_id=id))
        db.session.commit()

        flash(f"Ticket #{id} deleted successfully.", "danger")

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify(success=True)
        return redirect(url_for("tickets.list_tickets"))
    except Exception as e:
        flash(f"Error deleting ticket: {str(e)}", "danger")
        return redirect(url_for("tickets.list_tickets"))
    except Exception as e:
        flash(f"Error deleting ticket: {str(e)}", "danger")
        return redirect(url_for("tickets.list_tickets"))


# ============================================================
# DOWNLOAD ATTACHMENT
# ============================================================
@tickets_bp.route("/tickets/attachments/<path:filename>")
@login_required
def download_ticket_attachment(filename):
    # Find attachment by its web path suffix
    path_value = f"/tickets/attachments/{filename}"
    attachment = Attachment.query.filter(Attachment.filepath == path_value).first_or_404()
    ticket = Ticket.query.get_or_404(attachment.ticket_id)

    # Authorization similar to viewing a ticket
    allowed = False
    if current_user.role == "admin":
        allowed = True
    elif current_user.role == "manager":
        dept_user_ids = {u.id for u in User.query.filter_by(department=current_user.department).all()}
        if (
            ticket.created_by == current_user.id
            or ticket.assigned_to == current_user.id
            or (ticket.created_by in dept_user_ids)
            or (ticket.assigned_to in dept_user_ids)
        ):
            allowed = True
    else:
        if ticket.created_by == current_user.id or ticket.assigned_to == current_user.id:
            allowed = True

    if not allowed:
        flash("You are not authorized to access this attachment.", "danger")
        abort(403)

    upload_folder = _ensure_ticket_upload_folder()
    return send_from_directory(
        upload_folder,
        filename,
        as_attachment=True,
        download_name=(attachment.filename or os.path.basename(filename)),
    )


# ============================================================
# ARCHIVE
# ============================================================
@tickets_bp.route("/tickets/<int:ticket_id>/archive", methods=["POST"])
@login_required
def archive_ticket(ticket_id: int):
    ticket = Ticket.query.get_or_404(ticket_id)
    if not _user_can_archive_ticket(ticket):
        flash(_("You are not authorized to archive this ticket."), "danger")
        abort(403)
    if (ticket.status or "").lower() != "closed":
        msg = _("Only closed tickets can be archived.")
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify(success=False, message=msg), 400
        flash(msg, "warning")
        return redirect(request.referrer or url_for("tickets.list_tickets"))
    try:
        archive_entry = build_archive_from_ticket(ticket, current_user.id)
        db.session.add(archive_entry)
        db.session.delete(ticket)
        db.session.commit()
        success_msg = _("Ticket #%d archived successfully.") % ticket.id
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify(success=True, message=success_msg)
        flash(success_msg, "success")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to archive ticket %s", ticket_id)
        error_msg = _("Unable to archive this ticket. Please try again.")
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify(success=False, message=error_msg), 500
        flash(error_msg, "danger")
    return redirect(request.referrer or url_for("tickets.list_tickets"))


@tickets_bp.route("/tickets/archives")
@login_required
def list_ticket_archives():
    query = TicketArchive.query
    if current_user.role == "admin":
        pass
    elif current_user.role == "manager":
        dept_subq = (
            User.query.filter_by(department=current_user.department)
            .with_entities(User.id)
            .subquery()
        )
        query = query.filter(
            or_(
                TicketArchive.created_by.in_(dept_subq),
                TicketArchive.assigned_to.in_(dept_subq),
            )
        )
    else:
        query = query.filter(
            or_(
                TicketArchive.created_by == current_user.id,
                TicketArchive.assigned_to == current_user.id,
                TicketArchive.archived_by == current_user.id,
            )
        )
    archives = query.order_by(TicketArchive.archived_at.desc()).all()
    return render_template("tickets/archive_list.html", archives=archives)


@tickets_bp.route("/tickets/archives/<int:archive_id>")
@login_required
def view_ticket_archive(archive_id: int):
    archive = TicketArchive.query.get_or_404(archive_id)
    if not _can_view_archive(archive):
        flash(_("You cannot view this archived ticket."), "danger")
        abort(403)
    return render_template("tickets/archive_detail.html", archive=archive)


@tickets_bp.route("/tickets/archives/<int:archive_id>/attachments/<int:attachment_index>/download")
@login_required
def download_archived_attachment(archive_id: int, attachment_index: int):
    archive = TicketArchive.query.get_or_404(archive_id)
    if not _can_view_archive(archive):
        flash(_("You are not authorized to access this archived ticket."), "danger")
        abort(403)

    attachments = archive.attachments or []
    if attachment_index < 0 or attachment_index >= len(attachments):
        abort(404)

    attachment = attachments[attachment_index] or {}
    path_value = (attachment.get("filepath") or "").strip()
    download_label = attachment.get("filename") or os.path.basename(path_value) or _("attachment")
    source = request.args.get("source")
    if not path_value:
        flash(_("Attachment reference is missing."), "warning")
        return _archive_detail_redirect(source, archive)

    upload_folder = _ensure_ticket_upload_folder()
    static_upload_dir = os.path.join(
        os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")),
        "static",
        "uploads",
    )

    candidate_paths = []
    if path_value.startswith("/tickets/attachments/"):
        stored_name = os.path.basename(path_value)
        if stored_name:
            candidate_paths.append(("instance", upload_folder, stored_name))
    elif path_value.startswith("/static/uploads/"):
        stored_name = os.path.basename(path_value)
        if stored_name:
            candidate_paths.append(("static", static_upload_dir, stored_name))
    else:
        if os.path.isabs(path_value):
            candidate_paths.append(("absolute", None, path_value))
        stored_name = os.path.basename(path_value)
        if stored_name:
            candidate_paths.append(("instance", upload_folder, stored_name))

    for path_kind, directory, value in candidate_paths:
        if path_kind == "absolute":
            if os.path.exists(value):
                return send_file(value, as_attachment=True, download_name=download_label)
            continue
        full_path = os.path.join(directory, value)
        if os.path.exists(full_path):
            return send_from_directory(directory, value, as_attachment=True, download_name=download_label)

    flash(_("Attachment file could not be located on the server."), "warning")
    return _archive_detail_redirect(source, archive)
