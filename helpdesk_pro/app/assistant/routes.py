# -*- coding: utf-8 -*-
"""
Assistant widget API routes.
Provides a lightweight proxy to ChatGPT or custom webhooks.
"""

import json
from typing import List, Dict, Any

import requests
from flask import Blueprint, jsonify, request, abort
from flask_login import login_required, current_user
from flask_babel import gettext as _

from app import csrf
from app.models import AssistantConfig
from app.navigation import is_feature_allowed

assistant_bp = Blueprint("assistant", __name__, url_prefix="/assistant")
csrf.exempt(assistant_bp)


def _load_config():
    config = AssistantConfig.get()
    if not config or not config.is_enabled:
        return None
    return config


def _build_history(messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    valid = []
    for msg in messages or []:
        role = msg.get("role")
        content = msg.get("content")
        if role in {"user", "assistant", "system"} and isinstance(content, str):
            valid.append({"role": role, "content": content})
    return valid


@assistant_bp.route("/api/message", methods=["POST"])
@login_required
def api_message():
    if not is_feature_allowed("assistant_widget", current_user):
        abort(403)

    config = _load_config()
    if not config:
        return jsonify({"success": False, "message": _("Assistant is disabled.")}), 400

    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    history = _build_history(data.get("history", []))
    if not message:
        return jsonify({"success": False, "message": _("Message cannot be empty.")}), 400

    history.append({"role": "user", "content": message})

    try:
        if config.provider == "chatgpt":
            if not config.openai_api_key:
                return jsonify({"success": False, "message": _("OpenAI API key is not configured.")}), 400
            reply = _call_openai(history, config)
        else:
            if not config.webhook_url:
                return jsonify({"success": False, "message": _("Webhook URL is not configured.")}), 400
            reply = _call_webhook(history, config)
    except requests.RequestException as exc:
        return jsonify({"success": False, "message": _("Connection error: %(error)s", error=str(exc))}), 502
    except Exception as exc:  # pragma: no cover
        return jsonify({"success": False, "message": str(exc)}), 500

    if not reply:
        return jsonify({"success": False, "message": _("Assistant did not return a reply.")}), 502

    history.append({"role": "assistant", "content": reply})
    return jsonify({"success": True, "reply": reply, "history": history})


def _call_openai(history: List[Dict[str, str]], config: AssistantConfig) -> str:
    endpoint = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.openai_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.openai_model or "gpt-3.5-turbo",
        "messages": history,
    }
    response = requests.post(endpoint, headers=headers, json=payload, timeout=30)
    if response.status_code >= 400:
        raise RuntimeError(_("OpenAI error: %(status)s %(body)s", status=response.status_code, body=response.text))
    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        return ""
    return choices[0].get("message", {}).get("content", "").strip()


def _call_webhook(history: List[Dict[str, str]], config: AssistantConfig) -> str:
    payload = {
        "history": history,
        "current_user": {
            "id": current_user.id,
            "username": current_user.username,
            "role": current_user.role,
        },
        "latest": history[-1],
    }
    method = (config.webhook_method or "POST").upper()
    headers = {"Content-Type": "application/json"}
    headers.update(config.webhook_headers_data())
    if method == "GET":
        response = requests.get(config.webhook_url, params={"payload": json.dumps(payload)}, headers=headers, timeout=30)
    else:
        response = requests.request(method, config.webhook_url, headers=headers, json=payload, timeout=30)
    if response.status_code >= 400:
        raise RuntimeError(_("Webhook error: %(status)s %(body)s", status=response.status_code, body=response.text))
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(_("Invalid webhook response: %(error)s", error=str(exc)))
    reply = data.get("reply")
    if isinstance(reply, str):
        return reply.strip()
    raise RuntimeError(_("Webhook response is missing a 'reply' field."))
