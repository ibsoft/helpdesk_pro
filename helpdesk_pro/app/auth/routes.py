from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from flask_login import login_user, logout_user, login_required, current_user
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from flask_mail import Message
from sqlalchemy import func
from urllib.parse import urlparse, urljoin

from app import db, login_manager
from app.models.user import User
from app.models.auth_config import AuthConfig
from app.utils.security import validate_password_strength
from flask_babel import gettext as _
from app.mail_utils import queue_mail_with_optional_auth


auth_bp = Blueprint("auth", __name__)


def _is_safe_redirect(target: str) -> bool:
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return (
        test_url.scheme in {"http", "https"}
        and ref_url.netloc == test_url.netloc
    )


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if not User.query.first():
        return redirect(url_for("auth.setup_admin"))
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        user = User.query.filter_by(username=username).first()
        if not user or not user.active or not user.check_password(password):
            flash(_("Incorrect credentials."), "danger")
        elif not user.active:
            flash(_("Account is disabled."), "danger")
        else:
            remember = bool(request.form.get("remember"))
            login_user(user, remember=remember)
            display_name = user.full_name or user.username
            flash(_("Welcome, %(username)s!", username=display_name), "success")
            next_url = request.args.get("next")
            if next_url and _is_safe_redirect(next_url):
                return redirect(next_url)
            return redirect(url_for("dashboard.index"))
    return render_template("auth/login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash(_("You have been logged out."), "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    config = AuthConfig.load()
    allow_reset = bool(config.allow_password_reset)
    email_sent = False

    if request.method == "POST" and not allow_reset:
        flash(_("Password reset is disabled."), "warning")
    elif request.method == "POST" and allow_reset:
        email = (request.form.get("email") or "").strip().lower()
        if email:
            user = (
                User.query.filter(func.lower(User.email) == email)
                .filter(User.active.is_(True))
                .first()
            )
            if user:
                try:
                    _send_password_reset_email(user)
                except Exception as exc:  # pragma: no cover
                    current_app.logger.exception("Failed to send reset email: %s", exc)
            email_sent = True
        else:
            flash(_("Please provide an email address."), "warning")

    return render_template(
        "auth/forgot_password.html",
        allow_reset=allow_reset,
        email_sent=email_sent,
    )


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    config = AuthConfig.load()
    allow_registration = bool(config.allow_self_registration)
    config.ensure_valid_role()

    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        if not allow_registration:
            flash(_("Registration is currently disabled."), "warning")
            return redirect(url_for("auth.register"))

        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        full_name = (request.form.get("full_name") or "").strip()
        password = request.form.get("password") or ""
        confirm_password = request.form.get("confirm_password") or ""

        errors = []
        if len(username) < 3:
            errors.append(_("Username must be at least 3 characters long."))
        if not email:
            errors.append(_("Email is required."))
        if User.query.filter(func.lower(User.username) == username.lower()).first():
            errors.append(_("Username is already taken."))
        if User.query.filter(func.lower(User.email) == email).first():
            errors.append(_("An account with that email already exists."))
        ok, password_errors = validate_password_strength(password)
        if not ok:
            errors.extend([_(msg) for msg in password_errors])
        if password != confirm_password:
            errors.append(_("Passwords do not match."))

        if errors:
            for msg in errors:
                flash(msg, "danger")
            return render_template(
                "auth/register.html",
                allow_registration=allow_registration,
            )

        user = User(
            username=username,
            email=email,
            full_name=full_name or None,
            role=config.default_role,
            active=True,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash(_("Account created successfully. You can now sign in."), "success")
        return redirect(url_for("auth.login"))

    return render_template(
        "auth/register.html",
        allow_registration=allow_registration,
    )


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    config = AuthConfig.load()
    if not config.allow_password_reset:
        flash(_("Password reset is disabled."), "warning")
        return redirect(url_for("auth.login"))

    user = _load_user_from_token(token)
    if not user:
        return render_template("auth/reset_password.html", token_invalid=True)

    if request.method == "POST":
        password = request.form.get("password") or ""
        confirm_password = request.form.get("confirm_password") or ""
        ok, password_errors = validate_password_strength(password)
        if not ok:
            for msg in password_errors:
                flash(_(msg), "danger")
        elif password != confirm_password:
            flash(_("Passwords do not match."), "danger")
        else:
            user.set_password(password)
            db.session.commit()
            flash(_("Your password has been updated. Please sign in."), "success")
            return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html", token_invalid=False)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@auth_bp.route("/setup", methods=["GET", "POST"])
def setup_admin():
    """First-run admin setup route."""
    if User.query.first():
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        email = (request.form.get("email") or "").strip()
        full_name = (request.form.get("full_name") or "").strip()

        errors = []
        if not username:
            errors.append(_("Username is required."))
        if not password:
            errors.append(_("Password is required."))
        else:
            ok, password_errors = validate_password_strength(password)
            if not ok:
                errors.extend([_(msg) for msg in password_errors])

        if errors:
            for msg in errors:
                flash(msg, "danger")
            return redirect(url_for("auth.setup_admin"))

        admin = User(
            username=username,
            email=email or None,
            full_name=full_name or None,
            role="admin",
            active=True,
        )
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        flash(_("Administrator account created successfully."), "success")
        login_user(admin)
        return redirect(url_for("dashboard.index"))

    return render_template("auth/setup_admin.html")


def _get_serializer() -> URLSafeTimedSerializer:
    secret_key = current_app.config.get("SECRET_KEY")
    return URLSafeTimedSerializer(secret_key, salt="helpdesk-password-reset")


def _generate_reset_token(user: User) -> str:
    serializer = _get_serializer()
    return serializer.dumps({"user_id": user.id, "hash": user.password_hash})


def _load_user_from_token(token: str) -> User:
    serializer = _get_serializer()
    try:
        data = serializer.loads(token, max_age=3600)
    except (BadSignature, SignatureExpired):
        return None
    user_id = data.get("user_id")
    token_hash = data.get("hash")
    if not user_id or not token_hash:
        return None
    user = User.query.filter_by(id=user_id, active=True).first()
    if not user or user.password_hash != token_hash:
        return None
    return user


def _send_password_reset_email(user: User):
    token = _generate_reset_token(user)
    reset_url = url_for("auth.reset_password", token=token, _external=True)
    subject = _("Helpdesk Pro password reset")
    body = _(
        "Hello %(username)s,\n\n"
        "You requested a password reset for your Helpdesk Pro account. "
        "Click the link below to choose a new password (valid for 1 hour):\n\n"
        "%(reset_url)s\n\n"
        "If you did not request this change, please ignore this email.",
        username=user.username,
        reset_url=reset_url,
    )
    sender = current_app.config.get("MAIL_DEFAULT_SENDER") or current_app.config.get("MAIL_USERNAME")
    if not sender:
        current_app.logger.warning("MAIL_DEFAULT_SENDER is not configured; password reset email not sent.")
        return
    message = Message(subject=subject, recipients=[user.email], body=body, sender=sender)
    queue_mail_with_optional_auth(
        message,
        description=f"password reset email to {user.email}",
    )
