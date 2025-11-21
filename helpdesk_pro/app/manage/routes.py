# -*- coding: utf-8 -*-
"""
Manage blueprint routes (access control, admin utilities).
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, abort
from flask_login import login_required, current_user
from flask_babel import gettext as _
from sqlalchemy import or_

from app import db
from app.models import (
    MenuPermission,
    ModulePermission,
    AssistantConfig,
    AuthConfig,
    ApiClient,
    User,
    EmailIngestConfig,
    Ticket,
    TicketArchive,
    TicketComment,
    Attachment,
    AuditLog,
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
    get_module_access,
    require_module_write,
)
from app.mcp import start_mcp_server, stop_mcp_server, refresh_mcp_settings
from dotenv import dotenv_values, load_dotenv, set_key, unset_key
from config import Config
from app.tickets.archive_utils import build_archive_from_ticket


manage_bp = Blueprint("manage", __name__, url_prefix="/manage")


def _require_admin():
    if not current_user.is_authenticated or current_user.role != "admin":
        from flask import abort
        abort(403)


def _parse_iso(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


CONFIGURATION_SECTIONS = [
    {
        "key": "core",
        "title": _("Core Settings"),
        "icon": "fa fa-gears text-primary",
        "description": _("Secrets, database settings, and general application behavior."),
        "fields": [
            {
                "key": "SECRET_KEY",
                "label": _("Secret Key"),
                "type": "password",
                "default": "changeme",
                "placeholder": _("Auto-generated when empty"),
                "help": _("Used to sign sessions and JWTs. Keep this value private."),
                "sensitive": True,
            },
            {
                "key": "SQLALCHEMY_DATABASE_URI",
                "label": _("Database URI"),
                "type": "text",
                "placeholder": "postgresql+psycopg2://user:pass@host/dbname",
                "help": _("Full SQLAlchemy connection string to the primary database."),
            },
            {
                "key": "BASE_URL",
                "label": _("Base URL"),
                "type": "text",
                "placeholder": "https://helpdesk.example.com",
                "help": _("Public root URL used in generated links and downloads."),
            },
            {
                "key": "SQLALCHEMY_ECHO",
                "label": _("SQL Debug Logging"),
                "type": "bool",
                "default": False,
                "help": _("Enable verbose SQL logging for troubleshooting."),
            },
            {
                "key": "LOG_LEVEL",
                "label": _("Log Level"),
                "type": "select",
                "default": "INFO",
                "choices": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                "help": _("Controls the verbosity of application logs."),
            },
            {
                "key": "DEFAULT_LANGUAGE",
                "label": _("Default Language"),
                "type": "select",
                "default": "en",
                "choices": ["en", "el"],
                "help": _("Language used when the user has not chosen a preference."),
            },
        ],
    },
    {
        "key": "mail",
        "title": _("Email"),
        "icon": "fa fa-envelope text-warning",
        "description": _("SMTP credentials for outbound notifications."),
        "fields": [
            {
                "key": "MAIL_SERVER",
                "label": _("SMTP Server"),
                "type": "text",
                "placeholder": "smtp.example.com",
            },
            {
                "key": "MAIL_PORT",
                "label": _("SMTP Port"),
                "type": "int",
                "default": 587,
            },
            {
                "key": "MAIL_USE_TLS",
                "label": _("Use TLS"),
                "type": "bool",
                "default": True,
            },
            {
                "key": "MAIL_USERNAME",
                "label": _("SMTP Username"),
                "type": "text",
            },
            {
                "key": "MAIL_PASSWORD",
                "label": _("SMTP Password"),
                "type": "password",
                "sensitive": True,
            },
            {
                "key": "MAIL_FALLBACK_TO_NO_AUTH",
                "label": _("Retry Without SMTP AUTH"),
                "type": "bool",
                "default": True,
                "help": _("Attempt to resend without credentials when the SMTP server does not advertise AUTH."),
            },
        ],
    },
    {
        "key": "ui",
        "title": _("Interface"),
        "icon": "fa fa-display text-info",
        "description": _("Fine-tune the global UI scale and layout."),
        "fields": [
            {
                "key": "UI_FONT_SCALE",
                "label": _("Font Scale"),
                "type": "float",
                "default": 0.95,
                "help": _("Global font scaling factor."),
            },
            {
                "key": "UI_NAVBAR_HEIGHT",
                "label": _("Navbar Height"),
                "type": "float",
                "default": 30.0,
                "help": _("Height of the top navigation bar in pixels."),
            },
            {
                "key": "UI_FOOTER_HEIGHT",
                "label": _("Footer Height"),
                "type": "float",
                "default": 35.0,
                "help": _("Height of the footer in pixels."),
            },
            {
                "key": "UI_DATATABLE_HEADER_FONT_SIZE",
                "label": _("DataTable Header Font Size"),
                "type": "float",
                "default": 0.95,
                "help": _("Font size (rem) for DataTable headers."),
            },
        ],
    },
    {
        "key": "assistant",
        "title": _("Assistant"),
        "icon": "fa fa-robot text-success",
        "description": _("Control AI assistant behavior and safety limits."),
        "fields": [
            {
                "key": "ASSISTANT_ENABLE_LLM_OVERRIDE",
                "label": _("Allow LLM Override"),
                "type": "bool",
                "default": True,
                "help": _("Allow per-request overrides of the default LLM provider."),
            },
            {
                "key": "ASSISTANT_TOOL_CALL_DEPTH_LIMIT",
                "label": _("Tool Call Depth Limit"),
                "type": "int",
                "default": -1,
                "help": _("Maximum recursive depth for tool calls (-1 to disable limit)."),
            },
        ],
    },
    {
        "key": "mcp",
        "title": _("MCP Server"),
        "icon": "fa fa-server text-danger",
        "description": _("Manage the Model Context Protocol service connection."),
        "fields": [
            {
                "key": "MCP_ENABLED",
                "label": _("Enable MCP"),
                "type": "bool",
                "default": True,
            },
            {
                "key": "MCP_HOST",
                "label": _("MCP Host"),
                "type": "text",
                "default": "127.0.0.1",
            },
            {
                "key": "MCP_BASE_URL",
                "label": _("MCP Base URL"),
                "type": "text",
                "placeholder": "http://127.0.0.1:8081",
                "default": "http://127.0.0.1:8081",
                "help": _("Override the MCP endpoint base address for assistant integrations (defaults to embedded server)."),
            },
            {
                "key": "MCP_PORT",
                "label": _("MCP Port"),
                "type": "int",
                "default": 8081,
            },
            {
                "key": "MCP_DATABASE_URL",
                "label": _("MCP Database URL"),
                "type": "text",
                "placeholder": _("Optional separate database connection string."),
            },
            {
                "key": "MCP_LOG_LEVEL",
                "label": _("MCP Log Level"),
                "type": "select",
                "choices": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                "default": "INFO",
            },
            {
                "key": "MCP_ALLOWED_ORIGINS",
                "label": _("Allowed Origins"),
                "type": "list",
                "default": [],
                "help": _("One origin per line, stored as JSON."),
            },
            {
                "key": "MCP_MAX_ROWS",
                "label": _("Max Rows"),
                "type": "int",
                "default": 1000,
            },
            {
                "key": "MCP_REQUEST_TIMEOUT",
                "label": _("Request Timeout (s)"),
                "type": "int",
                "default": 10,
            },
            {
                "key": "MCP_KEEP_ALIVE",
                "label": _("Keep Alive (s)"),
                "type": "int",
                "default": 5,
            },
            {
                "key": "MCP_ACCESS_LOG",
                "label": _("Access Log"),
                "type": "bool",
                "default": False,
            },
        ],
    },
]


def _resolve_env_path():
    custom = current_app.config.get("ENV_FILE_PATH") or current_app.config.get("ENV_PATH")
    if custom:
        return Path(custom)
    # Application root is one level above app/ package
    return Path(current_app.root_path).parent / ".env"


def _apply_env_overrides(flask_app):
    """Update select config keys from current environment variables."""

    base_url = os.getenv("BASE_URL")
    mcp_base_url = os.getenv("MCP_BASE_URL")
    mail_server = os.getenv("MAIL_SERVER")
    mail_port = os.getenv("MAIL_PORT")
    mail_use_tls = os.getenv("MAIL_USE_TLS")
    mail_username = os.getenv("MAIL_USERNAME")
    mail_password = os.getenv("MAIL_PASSWORD")
    mail_fallback = os.getenv("MAIL_FALLBACK_TO_NO_AUTH")

    if base_url:
        flask_app.config["BASE_URL"] = base_url
    else:
        flask_app.config.pop("BASE_URL", None)

    if mcp_base_url:
        flask_app.config["MCP_BASE_URL"] = mcp_base_url
    else:
        flask_app.config.pop("MCP_BASE_URL", None)

    if mail_server is not None:
        trimmed = mail_server.strip()
        if trimmed:
            flask_app.config["MAIL_SERVER"] = trimmed
        else:
            flask_app.config.pop("MAIL_SERVER", None)
    else:
        flask_app.config.pop("MAIL_SERVER", None)

    if mail_port is not None:
        try:
            flask_app.config["MAIL_PORT"] = int(mail_port)
        except ValueError:
            current_app.logger.warning("Invalid MAIL_PORT value %s; keeping previous value.", mail_port)
    else:
        flask_app.config.pop("MAIL_PORT", None)

    if mail_use_tls is not None:
        flask_app.config["MAIL_USE_TLS"] = _is_truthy(mail_use_tls, default=True)
    else:
        flask_app.config.pop("MAIL_USE_TLS", None)

    if mail_username is not None:
        flask_app.config["MAIL_USERNAME"] = mail_username
    else:
        flask_app.config.pop("MAIL_USERNAME", None)

    if mail_password is not None:
        flask_app.config["MAIL_PASSWORD"] = mail_password
    else:
        flask_app.config.pop("MAIL_PASSWORD", None)

    if mail_fallback is not None:
        flask_app.config["MAIL_FALLBACK_TO_NO_AUTH"] = _is_truthy(mail_fallback, default=True)
    else:
        flask_app.config.pop("MAIL_FALLBACK_TO_NO_AUTH", None)


def _refresh_mail_settings(flask_app):
    """Reinitialize Flask-Mail with the latest configuration values."""
    from app import mail

    mail.init_app(flask_app)


def _is_truthy(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _format_default(field):
    if "default" not in field:
        return ""
    default_value = field["default"]
    if isinstance(default_value, list):
        return ", ".join(str(item) for item in default_value)
    return str(default_value)


def _mask(value):
    if not value:
        return ""
    return "***"


def _truncate(value, length=60):
    if value is None:
        return ""
    text = str(value)
    return text if len(text) <= length else text[: length - 3] + "..."


def _format_active_value(field, active_value):
    if active_value is None:
        return ""
    kind = field.get("type", "text")
    if kind == "bool":
        return _("Enabled") if _is_truthy(active_value) else _("Disabled")
    if kind == "list":
        if isinstance(active_value, (list, tuple)):
            return ", ".join(str(item) for item in active_value)
        try:
            parsed = json.loads(active_value)
            if isinstance(parsed, list):
                return ", ".join(str(item) for item in parsed)
        except (TypeError, json.JSONDecodeError):
            pass
    if field.get("sensitive"):
        return _mask(active_value)
    return _truncate(active_value)


def _parse_list_field(raw_value):
    if not raw_value:
        return ""
    stripped = raw_value.strip()
    if not stripped:
        return ""
    if stripped.startswith("["):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, list):
                return "\n".join(str(item) for item in parsed)
        except (TypeError, json.JSONDecodeError):
            pass
    lines = []
    for piece in stripped.replace("\r", "").splitlines():
        cleaned = piece.strip()
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines)


def _human_file_size(num_bytes):
    if num_bytes is None:
        return ""
    size = float(num_bytes)
    units = ["B", "KB", "MB", "GB", "TB"]
    for index, unit in enumerate(units):
        if size < 1024 or index == len(units) - 1:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{int(size)} B"


def _build_configuration_context(env_values, overrides=None, bool_overrides=None):
    overrides = overrides or {}
    bool_overrides = bool_overrides or {}
    sections = []
    total_fields = 0
    configured_fields = 0

    for section in CONFIGURATION_SECTIONS:
        section_copy = {k: v for k, v in section.items() if k != "fields"}
        field_contexts = []
        for field in section["fields"]:
            total_fields += 1
            field_copy = field.copy()
            key = field_copy["key"]
            kind = field_copy.get("type", "text")
            env_raw = env_values.get(key)
            if env_raw not in (None, ""):
                configured_fields += 1
            default_display = _format_default(field_copy)
            active_value = current_app.config.get(key)
            field_copy["default_display"] = default_display
            field_copy["active_display"] = _format_active_value(field_copy, active_value)
            field_copy["configured"] = env_raw not in (None, "")
            if kind == "bool":
                if key in bool_overrides:
                    field_copy["checked"] = bool_overrides[key]
                else:
                    field_copy["checked"] = _is_truthy(env_raw, field_copy.get("default", False))
            elif kind == "list":
                if key in overrides:
                    field_copy["value"] = overrides[key]
                else:
                    field_copy["value"] = _parse_list_field(env_raw)
            else:
                if key in overrides:
                    field_copy["value"] = overrides[key]
                elif env_raw not in (None, ""):
                    field_copy["value"] = env_raw
                else:
                    field_copy["value"] = ""
            field_contexts.append(field_copy)
        section_copy["fields"] = field_contexts
        sections.append(section_copy)

    summary = {
        "total_fields": total_fields,
        "configured_fields": configured_fields,
    }
    return sections, summary

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

    menu_override_count = MenuPermission.query.filter_by(user_id=None).count()
    module_override_count = ModulePermission.query.count()
    module_read_only = ModulePermission.query.filter_by(access_level="read").count()

    return render_template(
        "manage/access.html",
        menu_items=display_items,
        roles=AVAILABLE_ROLES,
        module_items=module_items,
        module_levels=MODULE_ACCESS_LEVELS,
        menu_stats={
            "total_items": len(display_items),
            "overrides": menu_override_count,
            "roles": len(AVAILABLE_ROLES),
        },
        module_stats={
            "total_modules": len(module_items),
            "overrides": module_override_count,
            "read_only": module_read_only,
        },
    )


@manage_bp.route("/assistant", methods=["GET", "POST"])
@login_required
def assistant_settings():
    _require_admin()

    config = AssistantConfig.load()

    if request.method == "POST":
        config.is_enabled = bool(request.form.get("is_enabled"))
        previous_mcp_enabled = current_app.config.get("MCP_ENABLED", True)
        mcp_enabled_form = bool(request.form.get("mcp_enabled"))
        current_app.config["MCP_ENABLED"] = mcp_enabled_form

        provider = request.form.get("provider") or "chatgpt_hybrid"
        if provider in {"chatgpt", "builtin"}:
            provider = "chatgpt_hybrid"
        if provider not in {"chatgpt_hybrid", "openwebui", "webhook"}:
            provider = "chatgpt_hybrid"
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

        if provider == "chatgpt_hybrid":
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

        app_obj = current_app._get_current_object()
        ext_state = app_obj.extensions.setdefault("mcp_server", {"started": False})
        if mcp_enabled_form and not previous_mcp_enabled:
            start_mcp_server(app_obj)
            ext_state["started"] = True
        elif not mcp_enabled_form and previous_mcp_enabled:
            stop_mcp_server(app_obj)
            ext_state["started"] = False

        db.session.add(config)
        db.session.commit()
        flash(_("Assistant settings saved."), "success")
        return redirect(url_for("manage.assistant_settings"))

    headers_pretty = ""
    if config.webhook_headers:
        try:
            headers_pretty = json.dumps(json.loads(config.webhook_headers), indent=2)
        except Exception:
            headers_pretty = config.webhook_headers

    mcp_host = current_app.config.get("MCP_HOST", "127.0.0.1")
    mcp_port = current_app.config.get("MCP_PORT", 8081)
    mcp_base_url = current_app.config.get("MCP_BASE_URL") or f"http://{mcp_host}:{mcp_port}"
    mcp_defaults = {
        "enabled": current_app.config.get("MCP_ENABLED", True),
        "host": mcp_host,
        "port": mcp_port,
        "base_url": mcp_base_url,
        "allowed_origins": current_app.config.get("MCP_ALLOWED_ORIGINS", []),
        "log_level": current_app.config.get("MCP_LOG_LEVEL", current_app.config.get("LOG_LEVEL", "INFO")),
    }

    return render_template(
        "manage/assistant_settings.html",
        config=config,
        headers_pretty=headers_pretty,
        mcp_defaults=mcp_defaults,
    )


@manage_bp.route("/configuration", methods=["GET", "POST"])
@login_required
def configuration():
    _require_admin()

    env_path = _resolve_env_path()
    env_exists = env_path.exists()
    env_values = dotenv_values(env_path) if env_exists else {}
    env_values = {key: value for key, value in env_values.items() if value is not None}

    flask_app = current_app._get_current_object()
    _apply_env_overrides(flask_app)

    form_overrides = {}
    bool_overrides = {}
    errors = []

    if request.method == "POST":
        action = request.form.get("action", "save")
        if action == "reload":
            load_dotenv(dotenv_path=env_path, override=True)
            flask_app.config.from_object(Config)
            _apply_env_overrides(flask_app)
            _refresh_mail_settings(flask_app)
            refresh_mcp_settings(flask_app)
            flash(_("Configuration reloaded from %(path)s.", path=str(env_path)), "success")
            return redirect(url_for("manage.configuration"))

        if action == "save":
            updates = []
            removals = []

            for section in CONFIGURATION_SECTIONS:
                for field in section["fields"]:
                    key = field["key"]
                    kind = field.get("type", "text")
                    target_value = None
                    field_error = False

                    if kind == "bool":
                        checked = request.form.get(key) == "on"
                        bool_overrides[key] = checked
                        target_value = "true" if checked else "false"
                    else:
                        raw_value = request.form.get(key, "")
                        if kind == "list":
                            form_overrides[key] = raw_value.replace("\r", "") if raw_value else ""
                        else:
                            form_overrides[key] = raw_value.strip() if isinstance(raw_value, str) else raw_value
                        trimmed = form_overrides[key] if isinstance(form_overrides[key], str) else ""

                        if kind == "select":
                            choices = field.get("choices", [])
                            if trimmed and choices and trimmed not in choices:
                                errors.append(_("Invalid value for %(field)s.", field=field["label"]))
                                field_error = True
                            else:
                                target_value = trimmed
                        elif kind == "int":
                            if trimmed == "":
                                target_value = ""
                            else:
                                try:
                                    target_value = str(int(trimmed))
                                except ValueError:
                                    errors.append(_("%(field)s must be an integer.", field=field["label"]))
                                    field_error = True
                        elif kind == "float":
                            if trimmed == "":
                                target_value = ""
                            else:
                                try:
                                    target_value = str(float(trimmed))
                                except ValueError:
                                    errors.append(_("%(field)s must be a number.", field=field["label"]))
                                    field_error = True
                        elif kind == "list":
                            cleaned = form_overrides[key]
                            if cleaned and cleaned.strip():
                                if cleaned.strip().startswith("["):
                                    try:
                                        parsed = json.loads(cleaned.strip())
                                        if not isinstance(parsed, list):
                                            raise ValueError
                                        entries = [str(item).strip() for item in parsed if str(item).strip()]
                                    except (json.JSONDecodeError, ValueError):
                                        errors.append(_("Provide a JSON array or one entry per line for %(field)s.", field=field["label"]))
                                        field_error = True
                                        entries = []
                                    else:
                                        target_value = json.dumps(entries)
                                else:
                                    entries = [
                                        line.strip()
                                        for line in cleaned.splitlines()
                                        if line.strip()
                                    ]
                                    target_value = json.dumps(entries) if entries else ""
                            else:
                                target_value = ""
                        else:
                            target_value = trimmed

                    if field_error:
                        continue

                    current_value = env_values.get(key)

                    if target_value == "" or target_value is None:
                        if current_value not in (None, ""):
                            removals.append(key)
                    else:
                        if current_value != target_value:
                            updates.append((key, target_value))

            if not errors:
                changes = 0
                for key in removals:
                    unset_key(str(env_path), key)
                    changes += 1
                for key, value in updates:
                    set_key(str(env_path), key, value, quote_mode="auto")
                    changes += 1

                if changes:
                    load_dotenv(dotenv_path=env_path, override=True)
                    flask_app.config.from_object(Config)
                    _apply_env_overrides(flask_app)
                    _refresh_mail_settings(flask_app)
                    refresh_mcp_settings(flask_app)
                    flash(_("Configuration saved (%(count)s changes).", count=changes), "success")
                else:
                    flash(_("No changes were necessary."), "info")
                return redirect(url_for("manage.configuration"))
            else:
                for err in errors:
                    flash(err, "danger")

    sections, summary = _build_configuration_context(env_values, form_overrides, bool_overrides)

    configured_pct = 0
    if summary["total_fields"]:
        configured_pct = int(round((summary["configured_fields"] / summary["total_fields"]) * 100))

    last_modified = None
    env_size = None
    if env_exists:
        stat = env_path.stat()
        last_modified = datetime.fromtimestamp(stat.st_mtime)
        env_size = stat.st_size

    env_info = {
        "path": str(env_path),
        "exists": env_exists,
        "last_modified": last_modified.strftime("%Y-%m-%d %H:%M:%S") if last_modified else None,
        "size_bytes": env_size,
        "size_display": _human_file_size(env_size),
    }

    summary.update({
        "configured_pct": configured_pct,
        "missing_fields": summary["total_fields"] - summary["configured_fields"],
    })

    return render_template(
        "manage/configuration.html",
        sections=sections,
        summary=summary,
        env_info=env_info,
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
    total_clients = len(clients)
    active_clients = sum(1 for client in clients if client.is_active())
    revoked_clients = total_clients - active_clients
    recent_threshold = datetime.utcnow() - timedelta(days=30)
    recently_used = sum(
        1
        for client in clients
        if client.last_used_at and client.last_used_at >= recent_threshold
    )

    return render_template(
        "manage/api_keys.html",
        clients=clients,
        users=users,
        new_key_value=new_key_value,
        api_stats={
            "total": total_clients,
            "active": active_clients,
            "revoked": revoked_clients,
            "recent": recently_used,
            "recent_days": 30,
        },
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


@manage_bp.route("/ticket-archives", methods=["GET", "POST"])
@login_required
def ticket_archives():
    access = get_module_access(current_user, "ticket_archives")
    if access not in {"read", "write"}:
        abort(403)
    can_archive = access == "write"
    can_restore = can_archive or current_user.role == "manager"
    windows = [
        ("day", _("Older than 1 day")),
        ("week", _("Older than 1 week")),
        ("month", _("Older than 1 month")),
        ("year", _("Older than 1 year")),
    ]
    window_map = {
        "day": timedelta(days=1),
        "week": timedelta(weeks=1),
        "month": timedelta(days=30),
        "year": timedelta(days=365),
    }
    if request.method == "POST":
        require_module_write("ticket_archives")
        scope = (request.form.get("scope") or "").strip().lower()
        if scope not in window_map:
            flash(_("Select a valid archive window."), "danger")
            return redirect(url_for("manage.ticket_archives"))
        cutoff = datetime.utcnow() - window_map[scope]
        tickets_query = Ticket.query.filter(Ticket.created_at <= cutoff).filter(Ticket.status == "Closed")
        tickets = tickets_query.all()
        archived = 0
        for ticket in tickets:
            archive_entry = build_archive_from_ticket(ticket, current_user.id)
            db.session.add(archive_entry)
            db.session.delete(ticket)
            archived += 1
        db.session.commit()
        flash(
            _("Archived %(count)s ticket(s) older than %(window)s.", count=archived, window=scope),
            "success" if archived else "info",
        )
        return redirect(url_for("manage.ticket_archives"))

    query = TicketArchive.query.filter(TicketArchive.status == "Closed")
    if current_user.role == "manager":
        dept_users = (
            User.query.filter_by(department=current_user.department)
            .with_entities(User.id)
            .subquery()
        )
        query = query.filter(
            or_(
                TicketArchive.created_by.in_(dept_users),
                TicketArchive.assigned_to.in_(dept_users),
            )
        )

    archives = query.order_by(TicketArchive.archived_at.desc()).all()
    status_counts = {
        "total": len(archives),
        "closed": sum(1 for a in archives if (a.status or "").lower() == "closed"),
    }
    owner_lookup = {}
    owner_ids = {a.created_by for a in archives if a.created_by}
    if owner_ids:
        owners = User.query.filter(User.id.in_(owner_ids)).all()
        owner_lookup = {u.id: u.username for u in owners}

    return render_template(
        "manage/ticket_archives.html",
        windows=windows,
        archives=archives,
        can_archive=can_archive,
        can_restore=can_restore,
        status_counts=status_counts,
        owner_lookup=owner_lookup,
    )


@manage_bp.get("/ticket-archives/<int:archive_id>")
@login_required
def ticket_archive_detail(archive_id: int):
    access = get_module_access(current_user, "ticket_archives")
    if access not in {"read", "write"}:
        abort(403)
    archive = TicketArchive.query.get_or_404(archive_id)
    owner_name = None
    if archive.created_by:
        owner = User.query.get(archive.created_by)
        owner_name = owner.username if owner else f"#{archive.created_by}"
    return render_template("manage/ticket_archive_detail.html", archive=archive, owner_name=owner_name)


@manage_bp.post("/ticket-archives/<int:archive_id>/restore")
@login_required
def restore_ticket_archive(archive_id: int):
    access = get_module_access(current_user, "ticket_archives")
    archive = TicketArchive.query.get_or_404(archive_id)
    if access != "write":
        if current_user.role != "manager":
            abort(403)
        dept_user_ids = {
            user_id
            for (user_id,) in User.query.filter_by(department=current_user.department)
            .with_entities(User.id)
            .all()
        }
        dept_allowed = False
        dept_name = (current_user.department or "").strip().lower()
        archive_dept = (archive.department or "").strip().lower()
        if dept_name and archive_dept and dept_name == archive_dept:
            dept_allowed = True
        if archive.created_by and archive.created_by in dept_user_ids:
            dept_allowed = True
        if archive.assigned_to and archive.assigned_to in dept_user_ids:
            dept_allowed = True
        if not dept_allowed:
            abort(403)
    else:
        require_module_write("ticket_archives")

    existing = Ticket.query.get(archive.ticket_id)
    if existing:
        flash(_("Ticket %(id)s already exists. Remove it before restoring.", id=archive.ticket_id), "warning")
        return redirect(url_for("manage.ticket_archives"))

    ticket = Ticket(
        subject=archive.subject,
        description=archive.description,
        priority=archive.priority,
        status=archive.status,
        department=archive.department,
        created_by=archive.created_by or current_user.id,
        assigned_to=archive.assigned_to,
        created_at=archive.created_at or datetime.utcnow(),
        updated_at=archive.updated_at or datetime.utcnow(),
        closed_at=archive.closed_at,
    )
    ticket.id = archive.ticket_id
    db.session.add(ticket)
    db.session.flush()

    for comment_data in archive.comments or []:
        comment = TicketComment(
            ticket_id=ticket.id,
            user=comment_data.get("user"),
            comment=comment_data.get("comment"),
            created_at=_parse_iso(comment_data.get("created_at")),
        )
        db.session.add(comment)

    for attachment_data in archive.attachments or []:
        attachment = Attachment(
            ticket_id=ticket.id,
            filename=attachment_data.get("filename"),
            filepath=attachment_data.get("filepath"),
            uploaded_by=attachment_data.get("uploaded_by"),
            uploaded_at=_parse_iso(attachment_data.get("uploaded_at")),
        )
        db.session.add(attachment)

    for log_data in archive.logs or []:
        log = AuditLog(
            action=log_data.get("action"),
            username=log_data.get("username"),
            ticket_id=ticket.id,
            timestamp=_parse_iso(log_data.get("timestamp")),
        )
        db.session.add(log)

    db.session.delete(archive)
    db.session.commit()
    flash(_("Ticket %(id)s restored from archive.", id=ticket.id), "success")
    return redirect(url_for("manage.ticket_archives"))
