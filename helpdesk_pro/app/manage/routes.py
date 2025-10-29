# -*- coding: utf-8 -*-
"""
Manage blueprint routes (access control, admin utilities).
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from flask_babel import gettext as _

from app import db
from app.models import (
    MenuPermission,
    ModulePermission,
    AssistantConfig,
    AuthConfig,
    ApiClient,
    User,
    EmailIngestConfig,
)
from app.models.assistant import DEFAULT_SYSTEM_PROMPT
from app.navigation import (
    MENU_DEFINITIONS,
    AVAILABLE_ROLES,
    flatten_menu,
    default_allowed,
    definition_map,
)
from app.permissions import (
    MODULE_ACCESS_DEFINITIONS,
    MODULE_ACCESS_LEVELS,
    clear_access_cache,
)


manage_bp = Blueprint("manage", __name__, url_prefix="/manage")


def _require_admin():
    if not current_user.is_authenticated or current_user.role != "admin":
        from flask import abort
        abort(403)


@manage_bp.route("/access", methods=["GET", "POST"])
@login_required
def access():
    _require_admin()

    flat_items = flatten_menu()
    definition_lookup = definition_map()

    if request.method == "POST":
        form_type = request.form.get("form_type", "menu")
        updated = False
        module_updated = False
        if form_type in {"menu", "all"}:
            for item in flat_items:
                item_key = item["key"]
                definition = definition_lookup.get(item_key, {})
                for role in AVAILABLE_ROLES:
                    field_name = f"perm_{item_key}_{role}"
                    selected = field_name in request.form
                    default = default_allowed(definition, type("obj", (object,), {"role": role})())
                    perm = MenuPermission.query.filter_by(menu_key=item_key, role=role, user_id=None).first()
                    if selected == default:
                        if perm:
                            db.session.delete(perm)
                            updated = True
                    else:
                        if perm:
                            if perm.allowed != selected:
                                perm.allowed = selected
                                updated = True
                        else:
                            db.session.add(MenuPermission(menu_key=item_key, role=role, allowed=selected))
                            updated = True
        if form_type in {"module", "all"}:
            for module_key in MODULE_ACCESS_DEFINITIONS.keys():
                default_level = "write"
                for role in AVAILABLE_ROLES:
                    field_name = f"module_perm_{module_key}_{role}"
                    level = request.form.get(field_name, default_level)
                    if level not in MODULE_ACCESS_LEVELS:
                        level = default_level
                    perm = ModulePermission.query.filter_by(module_key=module_key, role=role).first()
                    if level == default_level:
                        if perm:
                            db.session.delete(perm)
                            module_updated = True
                    else:
                        if perm:
                            if perm.access_level != level:
                                perm.access_level = level
                                module_updated = True
                        else:
                            db.session.add(
                                ModulePermission(module_key=module_key, role=role, access_level=level)
                            )
                            module_updated = True
            if module_updated:
                updated = True
        if updated:
            db.session.commit()
            clear_access_cache()
            flash(_("Access settings updated."), "success")
        else:
            flash(_("No changes were necessary."), "info")
        return redirect(url_for("manage.access"))

    # For GET, build display data (include defaults and overrides)
    display_items = []
    for item in flat_items:
        entry = {
            "key": item["key"],
            "label": item["label"],
            "has_children": item["has_children"],
            "roles": [],
        }
        for role in AVAILABLE_ROLES:
            definition = definition_lookup.get(item["key"], {})
            default = default_allowed(definition, type("obj", (object,), {"role": role})())
            perm = MenuPermission.query.filter_by(menu_key=item["key"], role=role, user_id=None).first()
            current = perm.allowed if perm is not None else default
            entry["roles"].append({
                "role": role,
                "current": current,
                "default": default,
            })
        display_items.append(entry)

    module_items = []
    for module_key, meta in MODULE_ACCESS_DEFINITIONS.items():
        module_entry = {
            "key": module_key,
            "label": meta.get("label", module_key.title()),
            "roles": [],
        }
        default_level = "write"
        for role in AVAILABLE_ROLES:
            perm = ModulePermission.query.filter_by(module_key=module_key, role=role).first()
            current = perm.access_level if perm is not None else default_level
            if current not in MODULE_ACCESS_LEVELS:
                current = default_level
            module_entry["roles"].append({
                "role": role,
                "current": current,
                "default": default_level,
            })
        module_items.append(module_entry)

    return render_template(
        "manage/access.html",
        menu_items=display_items,
        roles=AVAILABLE_ROLES,
        module_items=module_items,
        module_levels=MODULE_ACCESS_LEVELS,
    )


@manage_bp.route("/assistant", methods=["GET", "POST"])
@login_required
def assistant_settings():
    _require_admin()

    config = AssistantConfig.load()

    if request.method == "POST":
        config.is_enabled = bool(request.form.get("is_enabled"))
        provider = request.form.get("provider") or "builtin"
        if provider not in {"chatgpt", "chatgpt_hybrid", "webhook", "builtin", "openwebui"}:
            provider = "builtin"
        config.provider = provider

        position = request.form.get("position") or "right"
        if position not in {"left", "right"}:
            position = "right"
        config.position = position

        config.button_label = (request.form.get("button_label") or "Ask AI").strip()[:120]
        config.window_title = (request.form.get("window_title") or "AI Assistant").strip()[:120]
        config.welcome_message = (request.form.get("welcome_message") or "").strip()
        system_prompt = (request.form.get("system_prompt") or "").strip()
        config.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

        if provider in {"chatgpt", "chatgpt_hybrid"}:
            config.openai_api_key = (request.form.get("openai_api_key") or "").strip()
            config.openai_model = (request.form.get("openai_model") or "gpt-3.5-turbo").strip()
            config.openwebui_api_key = None
            config.openwebui_base_url = None
            config.openwebui_model = "gpt-3.5-turbo"
            config.webhook_url = None
            config.webhook_method = "POST"
            config.webhook_headers = None
        elif provider == "openwebui":
            config.openwebui_api_key = (request.form.get("openwebui_api_key") or "").strip() or None
            config.openwebui_base_url = (request.form.get("openwebui_base_url") or "").strip() or None
            config.openwebui_model = (request.form.get("openwebui_model") or "gpt-3.5-turbo").strip()
            config.openai_api_key = None
            config.openai_model = "gpt-3.5-turbo"
            config.webhook_url = None
            config.webhook_method = "POST"
            config.webhook_headers = None
        elif provider == "webhook":
            config.openai_api_key = None
            config.openai_model = "gpt-3.5-turbo"
            config.openwebui_api_key = None
            config.openwebui_base_url = None
            config.openwebui_model = "gpt-3.5-turbo"
            config.webhook_url = (request.form.get("webhook_url") or "").strip() or None
            config.webhook_method = (request.form.get("webhook_method") or "POST").strip().upper()
            headers_raw = (request.form.get("webhook_headers") or "").strip()
            if headers_raw:
                try:
                    import json
                    parsed = json.loads(headers_raw)
                    if isinstance(parsed, dict):
                        config.webhook_headers = json.dumps(parsed)
                    else:
                        flash(_("Webhook headers must be valid JSON object."), "warning")
                except Exception:
                    flash(_("Webhook headers must be valid JSON."), "warning")
            else:
                config.webhook_headers = None
        else:  # builtin
            config.openai_api_key = None
            config.openai_model = "gpt-3.5-turbo"
            config.openwebui_api_key = None
            config.openwebui_base_url = None
            config.openwebui_model = "gpt-3.5-turbo"
            config.webhook_url = None
            config.webhook_method = "POST"
            config.webhook_headers = None

        db.session.add(config)
        db.session.commit()
        flash(_("Assistant settings saved."), "success")
        return redirect(url_for("manage.assistant_settings"))

    import json

    headers_pretty = ""
    if config.webhook_headers:
        try:
            headers_pretty = json.dumps(json.loads(config.webhook_headers), indent=2)
        except Exception:
            headers_pretty = config.webhook_headers

    return render_template(
        "manage/assistant_settings.html",
        config=config,
        headers_pretty=headers_pretty,
    )


@manage_bp.route("/auth", methods=["GET", "POST"])
@login_required
def auth_settings():
    _require_admin()

    config = AuthConfig.load()

    if request.method == "POST":
        config.allow_self_registration = bool(request.form.get("allow_self_registration"))
        config.allow_password_reset = bool(request.form.get("allow_password_reset"))
        default_role = (request.form.get("default_role") or "user").strip().lower()
        if default_role not in AVAILABLE_ROLES:
            default_role = "user"
        config.default_role = default_role
        config.ensure_valid_role()
        db.session.add(config)
        db.session.commit()
        flash(_("Authentication settings saved."), "success")
        return redirect(url_for("manage.auth_settings"))

    return render_template(
        "manage/auth_settings.html",
        config=config,
        roles=AVAILABLE_ROLES,
    )


@manage_bp.route("/api", methods=["GET", "POST"])
@login_required
def api_keys():
    _require_admin()

    new_key_value = None
    client_id = None

    if request.method == "POST":
        action = request.form.get("action") or ""
        client_id = request.form.get("client_id")
        default_user_id = request.form.get("default_user_id") or None
        if default_user_id:
            try:
                default_user_id = int(default_user_id)
                if not User.query.get(default_user_id):
                    flash(_("Selected default user does not exist."), "warning")
                    default_user_id = None
            except (TypeError, ValueError):
                default_user_id = None

        try:
            if action == "create":
                name = (request.form.get("name") or _("New API Client")).strip()
                description = (request.form.get("description") or "").strip() or None
                client = ApiClient(name=name or _("New API Client"), description=description)
                if default_user_id:
                    client.default_user_id = default_user_id
                new_key_value = client.assign_new_secret()
                db.session.commit()
                flash(_("API key created. Copy it now, it will not be shown again."), "success")
            elif action == "rotate" and client_id:
                client = ApiClient.query.get(int(client_id))
                if not client:
                    flash(_("API client not found."), "warning")
                else:
                    if default_user_id:
                        client.default_user_id = default_user_id
                    new_key_value = client.assign_new_secret()
                    db.session.commit()
                    flash(_("API key rotated. Copy the new key immediately."), "success")
            elif action == "update" and client_id:
                client = ApiClient.query.get(int(client_id))
                if not client:
                    flash(_("API client not found."), "warning")
                else:
                    client.name = (request.form.get("name") or client.name).strip() or client.name
                    client.description = (request.form.get("description") or "").strip() or None
                    client.default_user_id = default_user_id
                    db.session.add(client)
                    db.session.commit()
                    flash(_("API client details updated."), "success")
            elif action == "revoke" and client_id:
                client = ApiClient.query.get(int(client_id))
                if not client:
                    flash(_("API client not found."), "warning")
                else:
                    client.revoke()
                    db.session.commit()
                    flash(_("API key revoked."), "info")
            elif action == "delete" and client_id:
                client = ApiClient.query.get(int(client_id))
                if not client:
                    flash(_("API client not found."), "warning")
                else:
                    db.session.delete(client)
                    db.session.commit()
                    flash(_("API client deleted."), "info")
            else:
                flash(_("Unsupported action."), "warning")
        except Exception as exc:  # pragma: no cover
            db.session.rollback()
            flash(_("Error processing request: %(error)s", error=str(exc)), "danger")

    clients = ApiClient.query.order_by(ApiClient.created_at.desc()).all()
    users = User.query.order_by(User.username.asc()).all()

    return render_template(
        "manage/api_keys.html",
        clients=clients,
        users=users,
        new_key_value=new_key_value,
    )


@manage_bp.route("/api/docs", methods=["GET"])
@login_required
def api_docs():
    _require_admin()
    spec_url = url_for("api.openapi_spec")
    return render_template("manage/api_docs.html", spec_url=spec_url)


@manage_bp.route("/email-ingest", methods=["GET", "POST"])
@login_required
def email_ingest():
    _require_admin()

    config = EmailIngestConfig.load()
    users = User.query.order_by(User.username.asc()).all()
    table_missing = getattr(config, "_table_missing", False)

    if request.method == "GET" and table_missing:
        flash(
            _(
                "Email ingestion is temporarily unavailable because the database schema is out of date. "
                "Please run the latest migrations and reload this page."
            ),
            "warning",
        )

    if request.method == "POST":
        if table_missing:
            flash(
                _(
                    "Unable to save email ingestion settings because the required database table "
                    "is missing. Run the database migrations and try again."
                ),
                "danger",
            )
            return redirect(url_for("manage.email_ingest"))
        action = (request.form.get("action") or "save").lower()
        if action == "run":
            from app.email2ticket.service import run_once
            try:
                processed = run_once(current_app)
                if processed:
                    flash(_("Processed %(count)s email(s) and created tickets.", count=processed), "success")
                else:
                    flash(_("Mailbox checked. No new emails were ingested."), "info")
            except Exception as exc:
                flash(_("Failed to process mailbox: %(error)s", error=str(exc)), "danger")
            return redirect(url_for("manage.email_ingest"))

        previous_creator = config.created_by_user_id
        config.update_from_form(request.form)

        validation_errors = []
        if config.is_enabled:
            if not config.host:
                validation_errors.append(_("Mail server host is required when email ingestion is enabled."))
            if not config.username:
                validation_errors.append(_("Mailbox username is required when email ingestion is enabled."))
            if not config.password:
                validation_errors.append(_("Mailbox password is required when email ingestion is enabled."))

        if validation_errors:
            db.session.rollback()
            config.created_by_user_id = previous_creator
            for message in validation_errors:
                flash(message, "danger")
            return redirect(url_for("manage.email_ingest"))
        if not config.created_by_user_id:
            db.session.rollback()
            config.created_by_user_id = previous_creator
            flash(_("Please select a ticket creator account."), "warning")
            return redirect(url_for("manage.email_ingest"))
        db.session.add(config)
        db.session.commit()

        from app.email2ticket.service import ensure_worker_running

        ensure_worker_running(current_app, reload_cfg=True)
        flash(_("Email ingestion settings saved."), "success")
        return redirect(url_for("manage.email_ingest"))

    password_placeholder = "***" if config.password else ""
    return render_template(
        "manage/email_ingest.html",
        config=config,
        users=users,
        password_placeholder=password_placeholder,
    )
