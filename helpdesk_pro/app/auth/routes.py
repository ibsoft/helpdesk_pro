import secrets

from authlib.integrations.base_client import OAuthError
from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from flask_login import login_user, logout_user, login_required, current_user
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from flask_mail import Message
from sqlalchemy import func
from urllib.parse import urlparse, urljoin
from ldap3 import Server, Connection, ALL
from ldap3.core.exceptions import LDAPException

from app import db, login_manager
from app.auth import oauth
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


AUTH_METHOD_LOCAL = "local"
AUTH_METHOD_LDAP = "ldap"
AUTH_METHOD_SSO = "sso"


def _form_auth_methods() -> list[str]:
    raw_methods = current_app.config.get("AUTH_METHODS") or ["local"]
    methods: list[str] = []
    for entry in raw_methods:
        method = (entry or "").strip().lower()
        if method == AUTH_METHOD_LDAP and not current_app.config.get("AUTH_LDAP_ENABLED"):
            continue
        if method in {AUTH_METHOD_LOCAL, AUTH_METHOD_LDAP}:
            if method not in methods:
                methods.append(method)
    if AUTH_METHOD_LOCAL not in methods:
        methods.insert(0, AUTH_METHOD_LOCAL)
    return methods


def _is_sso_configured() -> bool:
    cfg = current_app.config
    return all(
        (
            cfg.get("AUTH_SSO_ENABLED"),
            cfg.get("AUTH_SSO_CLIENT_ID"),
            cfg.get("AUTH_SSO_CLIENT_SECRET"),
            cfg.get("AUTH_SSO_METADATA_URL"),
        )
    )


def _get_selected_method(request_method: str, available_methods: list[str]) -> str:
    if request_method != "POST":
        return available_methods[0]
    requested = (request.form.get("auth_method") or "").strip().lower()
    if requested in available_methods:
        return requested
    return available_methods[0]


def _handle_successful_login(user: User, remember: bool):
    login_user(user, remember=remember)
    display_name = user.full_name or user.username
    flash(_("Welcome, %(username)s!", username=display_name), "success")
    next_url = request.args.get("next")
    if next_url and _is_safe_redirect(next_url):
        return redirect(next_url)
    return redirect(url_for("dashboard.index"))


def _get_or_create_external_user(
    username: str,
    email: str | None = None,
    full_name: str | None = None,
) -> User | None:
    username_value = (username or "").strip()
    if not username_value:
        return None
    email_value = (email or "").strip().lower() or None
    user = User.query.filter(func.lower(User.username) == username_value.lower()).first()
    if not user and email_value:
        user = User.query.filter(func.lower(User.email) == email_value).first()
    if user:
        if not user.active:
            return None
        updated = False
        if email_value and user.email.lower() != email_value:
            user.email = email_value
            updated = True
        if full_name and not user.full_name:
            user.full_name = full_name.strip() or None
            updated = True
        if updated:
            db.session.commit()
        return user
    if not email_value:
        domain = current_app.config.get("AUTH_LDAP_DEFAULT_EMAIL_DOMAIN") or "example.local"
        email_value = f"{username_value}@{domain}"
    auth_config = AuthConfig.load()
    external_user = User(
        username=username_value,
        email=email_value,
        full_name=full_name or None,
        role=auth_config.default_role,
        active=True,
    )
    external_user.set_password(secrets.token_urlsafe(40))
    db.session.add(external_user)
    db.session.commit()
    return external_user


def _ldap_authenticate(username: str, password: str) -> dict[str, str] | None:
    if not username or not password:
        return None
    if not current_app.config.get("AUTH_LDAP_ENABLED"):
        return None
    server_uri = current_app.config.get("AUTH_LDAP_SERVER_URI")
    if not server_uri:
        return None
    server = Server(
        server_uri,
        port=current_app.config.get("AUTH_LDAP_PORT", 389),
        use_ssl=current_app.config.get("AUTH_LDAP_USE_SSL", False),
        get_info=ALL,
    )
    bind_dn = current_app.config.get("AUTH_LDAP_BIND_DN")
    bind_password = current_app.config.get("AUTH_LDAP_BIND_PASSWORD")
    user_dn_template = current_app.config.get("AUTH_LDAP_USER_DN_TEMPLATE")
    user_dn: str | None = None
    email: str | None = None
    full_name: str | None = None
    search_conn = None
    try:
        if user_dn_template:
            user_dn = user_dn_template.format(username=username)
        else:
            search_base = current_app.config.get("AUTH_LDAP_SEARCH_BASE")
            if not search_base or not bind_dn or not bind_password:
                return None
            search_conn = Connection(server, user=bind_dn, password=bind_password, auto_bind=True)
            user_attr = current_app.config.get("AUTH_LDAP_USER_ATTRIBUTE", "sAMAccountName")
            filter_expression = f"({user_attr}={username})"
            search_conn.search(search_base, filter_expression, attributes=["mail", "displayName"])
            if not search_conn.entries:
                return None
            entry = search_conn.entries[0]
            user_dn = entry.entry_dn
            email = getattr(entry, "mail", None)
            if email:
                email = email.value
            full_name_attr = getattr(entry, "displayName", None)
            if full_name_attr:
                full_name = full_name_attr.value
    finally:
        if search_conn:
            search_conn.unbind()
    if not user_dn:
        return None
    user_conn = None
    try:
        user_conn = Connection(server, user=user_dn, password=password, auto_bind=True)
        return {
            "username": username,
            "email": email,
            "full_name": full_name,
        }
    except LDAPException:
        return None
    finally:
        if user_conn:
            user_conn.unbind()


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if not User.query.first():
        return redirect(url_for("auth.setup_admin"))
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    form_methods = _form_auth_methods()
    selected_method = _get_selected_method(request.method, form_methods)
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        remember = bool(request.form.get("remember"))
        if selected_method == AUTH_METHOD_LOCAL:
            if not username or not password:
                flash(_("Username and password are required."), "danger")
            else:
                user = User.query.filter_by(username=username).first()
                if not user:
                    flash(_("Incorrect credentials."), "danger")
                elif not user.active:
                    flash(_("Account is disabled."), "danger")
                elif not user.check_password(password):
                    flash(_("Incorrect credentials."), "danger")
                else:
                    return _handle_successful_login(user, remember)
        elif selected_method == AUTH_METHOD_LDAP:
            ldap_info = _ldap_authenticate(username, password)
            if not ldap_info:
                flash(_("Incorrect credentials."), "danger")
            else:
                user = _get_or_create_external_user(
                    ldap_info["username"],
                    ldap_info.get("email"),
                    ldap_info.get("full_name"),
                )
                if not user:
                    flash(_("Account is disabled."), "danger")
                else:
                    return _handle_successful_login(user, remember)
        else:
            flash(_("Unsupported authentication method."), "danger")
    return render_template(
        "auth/login.html",
        auth_methods=form_methods,
        selected_auth_method=selected_method,
        sso_enabled=_is_sso_configured()
        and AUTH_METHOD_SSO in current_app.config.get("AUTH_METHODS", []),
    )


@auth_bp.route("/sso/login")
def sso_login():
    available = current_app.config.get("AUTH_METHODS", [])
    if not _is_sso_configured() or AUTH_METHOD_SSO not in available:
        flash(_("SSO login is not configured."), "warning")
        return redirect(url_for("auth.login"))
    redirect_uri = url_for("auth.sso_callback", _external=True)
    return oauth.sso.authorize_redirect(redirect_uri)


@auth_bp.route("/sso/callback")
def sso_callback():
    if not _is_sso_configured():
        return redirect(url_for("auth.login"))
    try:
        token = oauth.sso.authorize_access_token()
    except OAuthError as exc:  # pragma: no cover
        current_app.logger.warning("SSO login error: %s", exc)
        flash(_("SSO login failed."), "danger")
        return redirect(url_for("auth.login"))
    user_info = oauth.sso.parse_id_token(token)
    if not user_info:
        flash(_("SSO response did not include a valid user profile."), "danger")
        return redirect(url_for("auth.login"))
    email_claim = current_app.config.get("AUTH_SSO_EMAIL_CLAIM", "email")
    username_claim = current_app.config.get("AUTH_SSO_USERNAME_CLAIM", "preferred_username")
    name_claim = current_app.config.get("AUTH_SSO_NAME_CLAIM", "name")
    email = user_info.get(email_claim)
    username = user_info.get(username_claim) or email or user_info.get("sub")
    full_name = user_info.get(name_claim)
    user = _get_or_create_external_user(username or email or user_info.get("sub"), email, full_name)
    if not user:
        flash(_("Account is disabled."), "danger")
        return redirect(url_for("auth.login"))
    return _handle_successful_login(user, remember=True)


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
