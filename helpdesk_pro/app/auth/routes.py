from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required
from app import db, login_manager
from app.models.user import User
from werkzeug.security import generate_password_hash


auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if not User.query.first():
        return redirect(url_for("auth.setup_admin"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        user = User.query.filter_by(username=username).first()
        if not user:
            flash("User not found.", "danger")
        elif not user.check_password(password):
            flash("Incorrect password.", "danger")
        else:
            login_user(user)
            flash(f"Welcome, {user.username}!", "success")
            return redirect(url_for("dashboard.index"))
    return render_template("auth/login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/forgot-password")
def forgot_password():
    return render_template("auth/forgot_password.html")


@auth_bp.route("/register")
def register():
    return render_template("auth/register.html")


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@auth_bp.route("/setup", methods=["GET", "POST"])
def setup_admin():
    """First-run admin setup route."""
    if User.query.first():
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        username = request.form.get("username").strip()
        password = request.form.get("password").strip()
        email = request.form.get("email").strip()

        if not username or not password:
            flash("Username and password required", "danger")
            return redirect(url_for("auth.setup_admin"))

        admin = User(
            username=username,
            email=email,
            role="admin",
            active=True,
            password_hash=generate_password_hash(password)
        )
        db.session.add(admin)
        db.session.commit()
        flash("Administrator account created successfully.", "success")
        login_user(admin)
        return redirect(url_for("dashboard.index"))

    return render_template("auth/setup_admin.html")
