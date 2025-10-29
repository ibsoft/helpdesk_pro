from flask import Blueprint, render_template, request, jsonify, abort
from flask_login import login_required, current_user
from app import db, csrf
from app.models.user import User
from app.utils.roles import role_required
from sqlalchemy import func

users_bp = Blueprint("users", __name__)


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
    username = request.form.get("username")
    email = request.form.get("email")
    password = request.form.get("password")
    password_confirm = request.form.get("password_confirm")
    role = request.form.get("role", "user")
    department = request.form.get("department", "")
    active_values = request.form.getlist("active")
    active_value = active_values[-1] if active_values else "1"

    if not username or not email or not password:
        return jsonify(success=False, message="Missing required fields"), 400

    if password != (password_confirm or ""):
        return jsonify(success=False, message="Passwords do not match"), 400

    if User.query.filter((func.lower(User.username) == username.lower()) | (func.lower(User.email) == email.lower())).first():
        return jsonify(success=False, message="User already exists"), 400

    user = User(
        username=username,
        email=email,
        role=role,
        department=department,
        active=active_value in {"1", "true", "on", "yes"},
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
    new_role = request.form.get("role", user.role)
    new_department = request.form.get("department", user.department)
    new_password = request.form.get("password", "").strip()
    new_password_confirm = request.form.get("password_confirm", "").strip()
    active_values = request.form.getlist("active")
    active_value = active_values[-1] if active_values else ("1" if user.active else "0")

    if not new_username or not new_email:
        return jsonify(success=False, message="Username and email are required"), 400

    # Prevent duplicate usernames
    if User.query.filter(func.lower(User.username) == new_username.lower(), User.id != id).first():
        return jsonify(success=False, message=f"Username '{new_username}' already exists"), 400

    if User.query.filter(func.lower(User.email) == new_email.lower(), User.id != id).first():
        return jsonify(success=False, message=f"Email '{new_email}' already exists"), 400

    user.username = new_username
    user.email = new_email
    user.role = new_role
    user.department = new_department
    user.active = active_value in {"1", "true", "on", "yes"}
    if new_password:
        if new_password != new_password_confirm:
            return jsonify(success=False, message="Passwords do not match"), 400
        user.set_password(new_password)

    db.session.commit()
    return jsonify(success=True, message="User updated successfully")


@csrf.exempt
@users_bp.route("/users/<int:id>/delete", methods=["POST"])
@login_required
@role_required('admin')
def delete_user(id):
    if current_user.id == id:
        return jsonify(error="You cannot delete your own account"), 400
    user = User.query.get_or_404(id)
    db.session.delete(user)
    db.session.commit()
    return jsonify(success=True)
