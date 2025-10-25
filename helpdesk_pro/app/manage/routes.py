# -*- coding: utf-8 -*-
"""
Manage blueprint routes (access control, admin utilities).
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_babel import gettext as _

from app import db
from app.models import MenuPermission, AssistantConfig
from app.models.assistant import DEFAULT_SYSTEM_PROMPT
from app.navigation import (
    MENU_DEFINITIONS,
    AVAILABLE_ROLES,
    flatten_menu,
    default_allowed,
    definition_map,
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
        updated = False
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
        if updated:
            db.session.commit()
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

    return render_template(
        "manage/access.html",
        menu_items=display_items,
        roles=AVAILABLE_ROLES,
    )


@manage_bp.route("/assistant", methods=["GET", "POST"])
@login_required
def assistant_settings():
    _require_admin()

    config = AssistantConfig.load()

    if request.method == "POST":
        config.is_enabled = bool(request.form.get("is_enabled"))
        provider = request.form.get("provider") or "builtin"
        if provider not in {"chatgpt", "chatgpt_hybrid", "webhook", "builtin"}:
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
            config.webhook_url = None
            config.webhook_method = "POST"
            config.webhook_headers = None
        elif provider == "webhook":
            config.openai_api_key = None
            config.openai_model = "gpt-3.5-turbo"
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
