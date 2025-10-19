from sqlalchemy import or_
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, abort
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app import db, csrf
from app.models.ticket import Ticket, TicketComment, Attachment, AuditLog
from app.models.user import User

tickets_bp = Blueprint("tickets", __name__)

UPLOAD_DIR = os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")),
    "static",
    "uploads"
)

LOCAL_TZ = ZoneInfo("Europe/Athens")


def to_local(dt):
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(LOCAL_TZ)


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
                role="technician", active=True).order_by(User.username).all()

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

            users = User.query.filter_by(
                role="technician", active=True, department=current_user.department
            ).order_by(User.username).all()

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

        msg = f"Ticket #{t.id} created successfully."
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            row_html = render_template("tickets/_row.html", t=t)
            return jsonify(success=True, message=msg, category="success", html=row_html)

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
            users = User.query.filter_by(
                role="technician", active=True).order_by(User.username).all()
        elif current_user.role == "manager":
            users = User.query.filter_by(
                role="technician", active=True, department=current_user.department
            ).order_by(User.username).all()
        else:
            users = []

        if request.method == "POST":
            ticket.subject = request.form.get("subject", ticket.subject)
            ticket.description = request.form.get(
                "description", ticket.description)
            ticket.priority = request.form.get("priority", ticket.priority)
            ticket.status = request.form.get("status", ticket.status)
            assigned_to_val = request.form.get("assigned_to")

            if current_user.role == "manager" and assigned_to_val:
                assigned_user = User.query.get(int(assigned_to_val))
                if not assigned_user or assigned_user.department != current_user.department:
                    msg = "Managers can assign only to users within their department."
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

            return jsonify(success=True, message=f"Ticket #{ticket.id} updated successfully.", category="success")

        # --- GET ---
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

        return render_template(
            "tickets/view.html",
            ticket=t,
            comments=comments_data,
            attachments=attachments_data,
            logs=logs_data
        )
    except Exception as e:
        flash(f"Error viewing ticket: {str(e)}", "danger")
        return redirect(url_for("tickets.list_tickets"))


# ============================================================
# COMMENT
# ============================================================
@csrf.exempt
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

        flash("Comment added successfully.", "success")
        return jsonify(success=True)
    except Exception as e:
        flash(f"Error adding comment: {str(e)}", "danger")
        return jsonify(error=str(e)), 500


# ============================================================
# UPLOAD
# ============================================================
@csrf.exempt
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

        os.makedirs(UPLOAD_DIR, exist_ok=True)
        filename = secure_filename(f.filename)
        full_path = os.path.join(UPLOAD_DIR, filename)
        f.save(full_path)
        web_path = f"/static/uploads/{filename}"

        a = Attachment(ticket_id=id, filename=filename,
                       filepath=web_path, uploaded_by=current_user.username)
        db.session.add(a)
        db.session.add(AuditLog(action="Upload File",
                                username=current_user.username, ticket_id=id))
        db.session.commit()

        flash(f"File '{filename}' uploaded successfully.", "success")
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
