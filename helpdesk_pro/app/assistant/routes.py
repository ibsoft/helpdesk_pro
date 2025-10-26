# -*- coding: utf-8 -*-
"""Assistant widget API routes.

This module now supports three providers:

- OpenAI ChatGPT (proxying to OpenAI's API)
- Custom webhooks
- Built-in tooling that answers by querying the local PostgreSQL database
  across Tickets, Knowledge Base, Inventory, and Network modules.
"""

import json
import re
import ipaddress
from datetime import date, timedelta
from typing import List, Dict, Any, Iterable, Optional, Tuple, Union

import requests
from flask import Blueprint, jsonify, request, abort, current_app, url_for
from flask_login import login_required, current_user
from flask_babel import gettext as _
from sqlalchemy import func, or_, and_
from sqlalchemy.orm import joinedload

from app import csrf
from app.models import (
    AssistantConfig,
    Ticket,
    KnowledgeArticle,
    KnowledgeAttachment,
    HardwareAsset,
    SoftwareAsset,
    Network,
    NetworkHost,
    User,
)
from app.models.assistant import DEFAULT_SYSTEM_PROMPT
from app.navigation import is_feature_allowed


CIDR_PATTERN = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}/\d{1,2}\b")
IP_ADDRESS_PATTERN = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
HOSTNAME_QUERY_PATTERN = re.compile(r"(?:hostname|host)\s+(?:named\s+)?([a-z0-9_.\-\:]+)", re.IGNORECASE)
MAC_QUERY_PATTERN = re.compile(r"(?:mac(?:\s+address)?)\s+(?:of|for|=)?\s*([0-9a-f:\-]{8,})", re.IGNORECASE)
TICKET_ID_PATTERN = re.compile(r"ticket\s+#?(\d+)|αιτημ(?:α|ατος)?\s*#?(\d+)", re.IGNORECASE)
USER_REF_PATTERN = re.compile(
    r"(?:assigned to|for|owner|user|ip\s+of|για|σε)\s+([a-z0-9_.\-άέήίόύώ\s]+)",
    re.IGNORECASE,
)
ASSET_TAG_PATTERN = re.compile(r"(?:asset|ετικέτα)\s+tag\s+#?([a-z0-9_.\-]+)", re.IGNORECASE)
HOSTNAME_PATTERN = re.compile(r"(?:hostname|όνομα\s+host)\s+([a-z0-9_.\-]+)", re.IGNORECASE)
SERIAL_PATTERN = re.compile(r"(?:serial|σειριακό)\s+#?([a-z0-9_.\-]+)", re.IGNORECASE)
SOFTWARE_TAG_PATTERN = re.compile(r"(?:license|software|app|άδεια|λογισμικό)\s+tag\s+#?([a-z0-9_.\-]+)", re.IGNORECASE)

STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "from",
    "this",
    "what",
    "where",
    "when",
    "which",
    "are",
    "was",
    "can",
    "you",
    "give",
    "show",
    "list",
    "tell",
    "about",
    "please",
    "help",
    "need",
    "information",
    "details",
    "lookup",
    "find",
    "me",
    "my",
    "latest",
    "assign",
    "assigned",
    "assignment",
    "assignments",
    "unassigned",
    "pdf",
    "file",
    "document",
}

OPEN_STATUS_VALUES = ["open", "in progress", "pending", "new", "reopened"]
CLOSED_STATUS_VALUES = ["closed", "resolved", "completed", "cancelled", "done"]
PRIORITY_LEVELS = ["critical", "urgent", "high", "medium", "low"]

TICKET_KEYWORDS = {
    "ticket", "tickets", "incident", "case", "request",
    "αίτημα", "αιτήματα", "εισιτήριο", "εισιτήρια", "υπόθεση"
}
TICKET_TEXT_STOP = {
    "ticket", "tickets", "incident", "incidents", "case", "cases", "request", "requests",
    "open", "closed", "pending", "progress", "status", "priority", "department",
    "assigned", "assign", "assignee", "me", "my", "today", "yesterday", "count", "how",
    "many", "list", "show", "find", "latest", "new", "update", "updated"
}
KNOWLEDGE_KEYWORDS = {
    "knowledge", "kb", "article", "articles", "procedure", "guide", "manual", "attachment", "attachments",
    "info", "information", "details",
    "γνωση", "γνώση", "γνώσεων", "άρθρο", "άρθρα", "διαδικασία", "οδηγία", "εγχειρίδιο", "συνημμένο", "συνημμένα"
}
SOFTWARE_KEYWORDS = {
    "software", "license", "licence", "application", "app", "subscription", "saas", "programme", "key", "keys", "product key", "serial", "serial number",
    "λογισμικό", "άδεια", "άδειες", "εφαρμογή", "εφαρμογές", "συνδρομή", "κλειδί", "κλειδιά", "σειριακό", "σειριακός"
}

HARDWARE_KEYWORDS = {
    "hardware", "device", "devices", "laptop", "desktop", "server", "asset", "equipment", "machine", "serial", "serial number", "asset tag",
    "υλικό", "συσκευή", "συσκευές", "υπολογιστής", "φορητός", "σταθερός", "server", "περιουσιακό", "εξοπλισμός", "σειριακό", "ετικέτα", "asset"
}
NETWORK_KEYWORDS = {
    "network", "subnet", "cidr", "vlan", "ip", "wifi",
    "δίκτυο", "υποδίκτυο", "cidr", "vlan", "ip", "ίπ", "δικτυο",
    "networks", "subnets"
}

NETWORK_HINT_STOPWORDS = {
    "map",
    "maps",
    "diagram",
    "diagrams",
    "topology",
    "topologies",
    "layout",
    "layouts",
    "overview",
    "summary",
    "details",
    "information",
    "info",
    "hosts",
    "host",
    "available",
    "addresses",
    "address",
    "ips",
    "ip",
    "list",
    "lists",
    "show",
    "find",
    "lookup",
    "questions",
    "question",
    "from",
    "database",
    "db",
    "inventory",
    "status",
    "update",
    "updates",
    "report",
    "reports",
    "what",
    "is",
    "the",
    "this",
    "that",
    "which",
    "who",
    "where",
    "gateway",
    "vlan",
    "site",
    "hosts",
    "host",
    "network",
    "subnet",
    "cidr",
}

NETWORK_HINT_BREAK_RE = re.compile(r"\b(for|with|from|of|to|in|on|about|regarding|covering|showing)\b", re.IGNORECASE)

SOFTWARE_SEARCH_COLUMNS = [
    SoftwareAsset.name,
    SoftwareAsset.vendor,
    SoftwareAsset.category,
    SoftwareAsset.version,
    SoftwareAsset.license_type,
    SoftwareAsset.license_key,
    SoftwareAsset.serial_number,
    SoftwareAsset.custom_tag,
    SoftwareAsset.platform,
    SoftwareAsset.environment,
    SoftwareAsset.status,
    SoftwareAsset.cost_center,
    SoftwareAsset.support_vendor,
    SoftwareAsset.support_email,
    SoftwareAsset.support_phone,
    SoftwareAsset.contract_url,
    SoftwareAsset.usage_scope,
    SoftwareAsset.deployment_notes,
]

SENSITIVE_LICENSE_TERMS = (
    "license key",
    "licence key",
    "product key",
    "serial number",
    "activation key",
    "activation code",
    "windows key",
    "software key",
    "cd key",
    "κλειδί",
    "σειριακό",
)

REFUSAL_MARKERS = (
    "unable to provide",
    "cannot provide",
    "can't provide",
    "not able to provide",
    "cannot help with that request",
    "can't help with that request",
)

BUILTIN_DEFAULT_RESPONSE = (
    "I can help with ticket summaries, knowledge base articles and attachments, inventory assignments, "
    "and network availability. For example: 'Show my open tickets today', 'Which articles mention VPN', "
    "'List hardware assigned to Alice', or 'Find an available IP in 192.168.1.0/24'."
)

LLM_TOOL_DEFINITIONS = [
    {
        "name": "query_tickets",
        "description": (
            "Look up ticket information from the Helpdesk Pro database. Use this to retrieve ticket summaries, "
            "counts, or details filtered by status, priority, department, assignee, or dates."
        ),
    },
    {
        "name": "query_knowledge_base",
        "description": (
            "Search knowledge base articles and attachments stored in Helpdesk Pro. Use this to find guides, "
            "procedures, or documents that match specific keywords or phrases."
        ),
    },
    {
        "name": "query_software_inventory",
        "description": (
            "Retrieve software asset records, including license keys and assignment details, from the Helpdesk Pro "
            "inventory."
        ),
    },
    {
        "name": "query_hardware_inventory",
        "description": (
            "Retrieve hardware asset records, including asset tags, hostnames, serials, and assignment details, "
            "from the Helpdesk Pro inventory."
        ),
    },
    {
        "name": "query_network_inventory",
        "description": (
            "Retrieve network details, including CIDR blocks, available IPs, host reservations, and assignments "
            "from the Helpdesk Pro network map."
        ),
    },
]

PHRASE_PATTERN = re.compile(
    r"(?:for|about|regarding|lookup|find|search for|αναζήτησε|βρες|για)\s+([a-z0-9\"'\\-\\s\\.]+)",
    re.IGNORECASE,
)
QUOTED_PATTERN = re.compile(r"\"([^\"]+)\"|'([^']+)'")

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


def _normalize_message_text(message: str) -> str:
    if not message:
        return ""
    replacements = {
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
    }
    return message.translate(str.maketrans(replacements))


def _safe_strip(value: Union[str, None], chars: Optional[str] = None) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip(chars) if chars else value.strip()


def _should_force_builtin(message: str) -> bool:
    lowered = (message or "").lower()
    if not lowered:
        return False
    if not any(keyword in lowered for keyword in SOFTWARE_KEYWORDS):
        return False
    return any(term in lowered for term in SENSITIVE_LICENSE_TERMS)


def _is_meaningful_builtin_reply(reply: Optional[str]) -> bool:
    if not reply:
        return False
    stripped = _safe_strip(reply)
    if not stripped:
        return False
    return stripped != BUILTIN_DEFAULT_RESPONSE


def _maybe_builtin_override(
    message: str,
    history: List[Dict[str, str]],
    user,
    reply: str,
    cached: Optional[str] = None,
) -> Optional[str]:
    if not _should_force_builtin(message):
        return None
    lowered_reply = (reply or "").lower()
    if not lowered_reply:
        return None
    if not any(marker in lowered_reply for marker in REFUSAL_MARKERS):
        return None
    builtin_reply = cached if _is_meaningful_builtin_reply(cached) else None
    if not builtin_reply:
        builtin_reply = _call_builtin(message, history, user)
    if _is_meaningful_builtin_reply(builtin_reply):
        current_app.logger.info("Assistant fallback: overriding LLM refusal with builtin software lookup.")
        return builtin_reply
    return None


def _dispatch_module_query(tool_name: str, message: str, user) -> str:
    message = _normalize_message_text(message)
    lowered = message.lower()
    if tool_name == "query_tickets":
        response = _answer_ticket_query(message, lowered, user)
        return response or "No tickets matched those filters."
    if tool_name == "query_knowledge_base":
        response = _answer_knowledge_query(message)
        return response or "No knowledge items matched those filters."
    if tool_name == "query_software_inventory":
        response = _answer_software_query(message, lowered, user)
        return response or "No software assets matched those filters."
    if tool_name == "query_hardware_inventory":
        response = _answer_hardware_query(message, lowered, user)
        return response or "No hardware assets matched those filters."
    if tool_name == "query_network_inventory":
        response = _answer_network_query(message, lowered, user)
        return response or "No network records matched those filters."
    return "Unsupported tool call."


@assistant_bp.route("/api/message", methods=["POST"])
@login_required
def api_message():
    if not is_feature_allowed("assistant_widget", current_user):
        abort(403)

    config = _load_config()
    if not config:
        return jsonify({"success": False, "message": _("Assistant is disabled.")}), 400

    data = request.get_json(silent=True) or {}
    message = _safe_strip(data.get("message"))
    history = _build_history(data.get("history", []))
    if not message:
        return jsonify({"success": False, "message": _("Message cannot be empty.")}), 400

    normalized_message = _normalize_message_text(message)
    message = normalized_message

    system_prompt = config.system_prompt or DEFAULT_SYSTEM_PROMPT
    history.append({"role": "user", "content": message})
    messages_for_model = [{"role": "system", "content": system_prompt}] + history if system_prompt else history

    reply: Optional[str] = None
    builtin_reply: Optional[str] = None
    used_llm_provider = False

    if config.provider in {"chatgpt", "chatgpt_hybrid"} and _should_force_builtin(message):
        builtin_reply = _call_builtin(message, history, current_user)
        if _is_meaningful_builtin_reply(builtin_reply):
            current_app.logger.info("Assistant bypassed LLM for sensitive software query.")
            reply = builtin_reply

    if reply is None:
        try:
            if config.provider == "chatgpt":
                if not config.openai_api_key:
                    return jsonify({"success": False, "message": _("OpenAI API key is not configured.")}), 400
                used_llm_provider = True
                reply = _call_openai(messages_for_model, config, allow_tools=False)
            elif config.provider == "chatgpt_hybrid":
                if not config.openai_api_key:
                    return jsonify({"success": False, "message": _("OpenAI API key is not configured.")}), 400
                tool_context = {
                    "user": current_user,
                    "history": history,
                    "latest_user_message": message,
                }
                used_llm_provider = True
                reply = _call_openai(messages_for_model, config, allow_tools=True, tool_context=tool_context)
            elif config.provider == "openwebui":
                if not config.openwebui_base_url:
                    return jsonify({"success": False, "message": _("OpenWebUI base URL is not configured.")}), 400
                tool_context = {
                    "user": current_user,
                    "history": history,
                    "latest_user_message": message,
                }
                used_llm_provider = True
                reply = _call_openwebui(messages_for_model, config, tool_context=tool_context)
            elif config.provider == "builtin":
                reply = _call_builtin(message, history, current_user)
            else:
                if not config.webhook_url:
                    return jsonify({"success": False, "message": _("Webhook URL is not configured.")}), 400
                reply = _call_webhook(history, messages_for_model, config, system_prompt)
        except requests.RequestException as exc:
            return jsonify({"success": False, "message": _("Connection error: %(error)s", error=str(exc))}), 502
        except Exception as exc:  # pragma: no cover
            return jsonify({"success": False, "message": str(exc)}), 500

    if not reply and config.provider in {"chatgpt", "chatgpt_hybrid", "openwebui"}:
        if not _is_meaningful_builtin_reply(builtin_reply):
            builtin_reply = _call_builtin(message, history, current_user)
        if _is_meaningful_builtin_reply(builtin_reply):
            current_app.logger.info("Assistant recovered missing LLM reply with builtin software lookup.")
            reply = builtin_reply

    if used_llm_provider and reply:
        override = _maybe_builtin_override(message, history, current_user, reply, cached=builtin_reply)
        if override:
            reply = override

    if not reply:
        return jsonify({"success": False, "message": _("Assistant did not return a reply.")}), 502

    history.append({"role": "assistant", "content": reply})
    return jsonify({"success": True, "reply": reply, "history": history})


def _call_openai(
    messages: List[Dict[str, str]],
    config: AssistantConfig,
    allow_tools: bool,
    tool_context: Optional[Dict[str, Any]] = None,
    depth: int = 0,
) -> str:
    endpoint = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.openai_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.openai_model or "gpt-3.5-turbo",
        "messages": messages,
    }
    if allow_tools:
        payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": (
                                    "Natural language description of what to retrieve, including any filters "
                                    "(ids, usernames, tags, statuses, dates, etc.)."
                                ),
                            }
                        },
                        "required": ["query"],
                    },
                },
            }
            for tool in LLM_TOOL_DEFINITIONS
        ]
        payload["tool_choice"] = "auto"
    response = requests.post(endpoint, headers=headers, json=payload, timeout=30)
    if response.status_code >= 400:
        raise RuntimeError(_("OpenAI error: %(status)s %(body)s", status=response.status_code, body=response.text))
    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message", {})
    tool_calls = message.get("tool_calls") if allow_tools else None
    if allow_tools and tool_calls:
        limit = _tool_call_limit()
        if limit >= 0 and depth >= limit:
            fallback = "Remote tool execution limit reached. Please respond directly with the information gathered so far."
            return _safe_strip(message.get("content", fallback)) or fallback
        new_messages = messages + [message]
        for call in tool_calls:
            result = _execute_tool_call(call, tool_context or {})
            new_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id") or "",
                    "content": result,
                }
            )
        return _call_openai(new_messages, config, allow_tools=True, tool_context=tool_context, depth=depth + 1)
    return _safe_strip(message.get("content", ""))


def _latest_user_message_from(messages: List[Dict[str, Any]]) -> str:
    for msg in reversed(messages or []):
        if msg.get("role") == "user":
            return _safe_strip(msg.get("content"))
    return ""


def _prepare_tool_context(
    tool_context: Optional[Dict[str, Any]],
    messages: List[Dict[str, str]],
) -> Dict[str, Any]:
    context = dict(tool_context or {})
    if not context.get("latest_user_message"):
        context["latest_user_message"] = _latest_user_message_from(messages)
    context.setdefault("history", messages)
    return context


def _tool_call_limit() -> int:
    """Return the maximum allowed tool recursion depth, or a negative value to disable."""
    try:
        limit = int(current_app.config.get("ASSISTANT_TOOL_CALL_DEPTH_LIMIT", 3))
    except (TypeError, ValueError):
        limit = 3
    return limit


def _execute_remote_openwebui_tool(
    config: AssistantConfig,
    tool_call: Dict[str, Any],
) -> str:
    base_url = (config.openwebui_base_url or "").rstrip("/")
    if not base_url:
        return "Remote tool execution failed: OpenWebUI base URL is missing."

    function = tool_call.get("function") or {}
    name = function.get("name")
    raw_args = function.get("arguments")
    try:
        args = json.loads(raw_args) if isinstance(raw_args, str) and raw_args else raw_args or {}
    except (ValueError, TypeError):
        args = {"raw": raw_args}

    endpoint = f"{base_url}/api/v1/tools/call"
    headers = {"Content-Type": "application/json"}
    if config.openwebui_api_key:
        headers["Authorization"] = f"Bearer {config.openwebui_api_key}"

    payload = {
        "name": name,
        "arguments": args,
        "tool_call_id": tool_call.get("id"),
    }

    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=30)
    except requests.RequestException as exc:
        return f"Remote tool execution failed for {name}: {exc}"

    if response.status_code >= 400:
        return _safe_strip(
            _("Remote tool execution failed: %(status)s %(body)s", status=response.status_code, body=response.text)
        )

    try:
        data = response.json()
    except ValueError as exc:
        return f"Remote tool execution returned invalid JSON: {exc}"

    for key in ("result", "output", "reply", "content", "data"):
        if key in data:
            value = data[key]
            if isinstance(value, (dict, list)):
                return json.dumps(value)
            return _safe_strip(str(value))

    return "Remote tool execution succeeded but returned no result."


def _call_openwebui(
    messages: List[Dict[str, str]],
    config: AssistantConfig,
    tool_context: Optional[Dict[str, Any]] = None,
    depth: int = 0,
) -> str:
    base_url = (config.openwebui_base_url or "").rstrip("/")
    if not base_url:
        raise RuntimeError(_("OpenWebUI base URL is not configured."))

    endpoint = f"{base_url}/api/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    if config.openwebui_api_key:
        headers["Authorization"] = f"Bearer {config.openwebui_api_key}"

    payload = {
        "model": config.openwebui_model or "gpt-3.5-turbo",
        "messages": messages,
        "stream": False,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": (
                                    "Natural language description of what to retrieve, including any filters "
                                    "(ids, usernames, tags, statuses, dates, etc.)."
                                ),
                            }
                        },
                        "required": ["query"],
                    },
                },
            }
            for tool in LLM_TOOL_DEFINITIONS
        ],
        "tool_choice": "auto",
    }

    response = requests.post(endpoint, headers=headers, json=payload, timeout=30)
    if response.status_code >= 400:
        raise RuntimeError(_("OpenWebUI error: %(status)s %(body)s", status=response.status_code, body=response.text))
    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message", {})
    tool_calls = message.get("tool_calls") or []
    if tool_calls:
        limit = _tool_call_limit()
        if limit >= 0 and depth >= limit:
            fallback = "Remote tool execution limit reached. Please respond directly with the information gathered so far."
            return _safe_strip(message.get("content", fallback)) or fallback
        context = _prepare_tool_context(tool_context, messages)
        new_messages = messages + [message]
        local_tool_names = {tool["name"] for tool in LLM_TOOL_DEFINITIONS}
        for call in tool_calls:
            name = (call.get("function") or {}).get("name") or ""
            if name in local_tool_names:
                result = _execute_tool_call(call, context)
            else:
                result = _execute_remote_openwebui_tool(config, call)
            new_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id") or name,
                    "content": result,
                }
            )
        return _call_openwebui(new_messages, config, tool_context=context, depth=depth + 1)

    content = _safe_strip(message.get("content", ""))
    if content:
        stripped = content.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                tool_candidate = json.loads(stripped)
            except ValueError:
                tool_candidate = None
            if isinstance(tool_candidate, dict) and "name" in tool_candidate:
                name = tool_candidate.get("name") or ""
                arguments = (
                    tool_candidate.get("args")
                    or tool_candidate.get("arguments")
                    or tool_candidate.get("parameters")
                    or {}
                )
                raw_arguments = json.dumps(arguments)
                tool_call = {
                    "id": tool_candidate.get("id") or name,
                    "function": {
                        "name": name,
                        "arguments": raw_arguments,
                    },
                }
                local_tool_names = {tool["name"] for tool in LLM_TOOL_DEFINITIONS}
                context = _prepare_tool_context(tool_context, messages)
                if name in local_tool_names:
                    return _execute_tool_call(tool_call, context)
                return _execute_remote_openwebui_tool(config, tool_call)
        return content
    return ""


def _call_webhook(
    history: List[Dict[str, str]],
    messages_with_system: List[Dict[str, str]],
    config: AssistantConfig,
    system_prompt: str,
) -> str:
    payload = {
        "history": history,
        "messages_with_system": messages_with_system,
        "system_prompt": system_prompt,
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
        return _safe_strip(reply)
    raise RuntimeError(_("Webhook response is missing a 'reply' field."))


def _execute_tool_call(tool_call: Dict[str, Any], context: Dict[str, Any]) -> str:
    function = tool_call.get("function") or {}
    name = function.get("name") or ""

    raw_args = function.get("arguments") or ""
    if isinstance(raw_args, dict):
        args = raw_args
    else:
        try:
            args = json.loads(raw_args) if raw_args else {}
        except (ValueError, TypeError):
            args = {"query": raw_args if isinstance(raw_args, str) else ""}

    query = args.get("query") or context.get("latest_user_message") or ""
    user = context.get("user")

    if not _safe_strip(query):
        return "No query provided for helpdesk lookup."

    if name not in {tool["name"] for tool in LLM_TOOL_DEFINITIONS}:
        return f"Unsupported tool call: {name}"

    try:
        result = _dispatch_module_query(name, query, user)
    except Exception as exc:
        return f"Error while querying database: {exc}"
    return result or "No matching records were found."


def _call_builtin(message: str, history: List[Dict[str, str]], user) -> str:
    """Answer simple operational questions by querying the local database."""

    lowered = message.lower()

    try:
        network_response = _answer_network_query(message, lowered, user)
    except Exception as exc:  # pragma: no cover
        current_app.logger.exception("Assistant network handler failed: %s", exc)
        network_response = ""
    if network_response:
        return network_response

    has_ticket = any(keyword in lowered for keyword in TICKET_KEYWORDS)
    has_knowledge = any(keyword in lowered for keyword in KNOWLEDGE_KEYWORDS)
    has_hardware = any(keyword in lowered for keyword in HARDWARE_KEYWORDS)
    has_software = any(keyword in lowered for keyword in SOFTWARE_KEYWORDS)
    force_software = _should_force_builtin(message)

    if has_ticket:
        ticket_response = _answer_ticket_query(message, lowered, user)
        if ticket_response:
            return ticket_response

    if has_knowledge:
        knowledge_response = _answer_knowledge_query(message)
        if knowledge_response:
            return knowledge_response

    if has_software:
        software_response = _answer_software_query(message, lowered, user)
        if software_response:
            return software_response

    if has_hardware and not force_software:
        hardware_response = _answer_hardware_query(message, lowered, user)
        if hardware_response:
            return hardware_response

    return BUILTIN_DEFAULT_RESPONSE


def _answer_network_query(message: str, lowered: str, user) -> Optional[str]:
    candidate: Optional[Network] = None
    query = Network.query.options(joinedload(Network.hosts))
    networks_list = query.all()

    cidr_match = CIDR_PATTERN.search(message)

    if cidr_match:
        cidr_value = cidr_match.group(0)
        candidate = _find_network_by_cidr(networks_list, cidr_value)

    if not candidate:
        name_match = re.search(r"(?:network|subnet|vlan)\s+([a-z0-9_.\-\s]+)", lowered)
        if name_match:
            raw_name = name_match.group(1) or ""
            normalized = _normalize_network_name_hint(raw_name)
            if normalized:
                candidate = _match_network_by_normalized(networks_list, normalized)

    if not candidate:
        leading_match = re.search(r"([a-z0-9_.\-\s]+)\s+(?:network|subnet|vlan)", lowered)
        if leading_match:
            raw_name = leading_match.group(1) or ""
            normalized = _normalize_network_name_hint(raw_name)
            if normalized:
                candidate = _match_network_by_normalized(networks_list, normalized)

    if not candidate:
        for phrase in _extract_candidate_phrases(message):
            normalized = _normalize_network_name_hint(phrase)
            if not normalized:
                continue
            candidate = _match_network_by_normalized(networks_list, normalized)
            if candidate:
                break

    if not candidate and lowered.endswith(" network"):
        suffix = lowered[:-8].strip()
        normalized = _normalize_network_name_hint(suffix)
        if normalized:
            candidate = _match_network_by_normalized(networks_list, normalized)

    if not candidate:
        keywords = _extract_keywords(message, extra_stop=NETWORK_HINT_STOPWORDS)
        if keywords:
            for keyword in keywords[:3]:
                candidate = _match_network_by_normalized(networks_list, keyword)
                if candidate:
                    break

    if not candidate:
        user_tokens = _extract_user_tokens(message)
        host_tokens = _extract_network_host_tokens(message)
        user_usernames: List[str] = []
        if user and getattr(user, "username", None):
            user_usernames.append(user.username)
        if user_tokens or user_usernames or host_tokens:
            conditions = []
            search_tokens: List[str] = []
            for token in list(user_tokens) + list(host_tokens):
                cleaned = _safe_strip(token)
                if cleaned:
                    search_tokens.append(cleaned)

            for token in search_tokens:
                lowered_token = token.lower()
                like = f"%{lowered_token}%"
                conditions.append(
                    or_(
                        func.lower(NetworkHost.assigned_to).ilike(like),
                        func.lower(NetworkHost.hostname).ilike(like),
                        func.lower(NetworkHost.ip_address).ilike(like),
                        func.lower(NetworkHost.mac_address).ilike(like),
                        func.lower(NetworkHost.device_type).ilike(like),
                        func.lower(NetworkHost.description).ilike(like),
                    )
                )
            for uname in user_usernames:
                if uname:
                    conditions.append(func.lower(NetworkHost.assigned_to) == uname.lower())

            if conditions:
                host_query = NetworkHost.query.join(Network)
                host_results = (
                    host_query.filter(or_(*conditions))
                    .order_by(func.lower(Network.name).asc(), NetworkHost.ip_address.asc())
                    .limit(25)
                    .all()
                )
                if host_results:
                    lines = []
                    for host in host_results:
                        network_label = host.network.name or host.network.cidr or f"Network #{host.network_id}"
                        hostname = host.hostname or "—"
                        assigned = host.assigned_to or "Unassigned"
                        mac = host.mac_address or "—"
                        device_type = host.device_type or "—"
                        reserved_flag = "Reserved" if host.is_reserved else "Available"
                        description = host.description or "—"
                        lines.append(
                            f"{host.ip_address} — {network_label}; hostname {hostname}; MAC {mac}; type {device_type}; "
                            f"assigned to {assigned}; status {reserved_flag}; notes {description}"
                        )
                    if len(host_results) == 25:
                        lines.append("…limited to first 25 matches.")
                    return "Network matches:\n" + "\n".join(lines)
                return "No network hosts matched those details."

        if any(term in lowered for term in NETWORK_KEYWORDS) or "cidr" in lowered or "ip" in lowered:
            networks = sorted(
                networks_list,
                key=lambda net: (net.updated_at or date.min),
                reverse=True,
            )[:20]
            if not networks:
                return "No networks are currently registered in the database."
            lines = []
            for net in networks:
                host_count = len(net.hosts)
            site = net.site or "n/a"
            vlan = net.vlan or "n/a"
            gateway = net.gateway or "n/a"
            summary = (
                f"{(net.name or 'Unnamed network')} ({net.cidr}) — network {net.network_address or 'n/a'}; "
                f"broadcast {net.broadcast_address or 'n/a'}; hosts tracked {host_count}; "
                f"gateway {gateway}; site {site}; VLAN {vlan}"
            )
            if net.description:
                summary += f"; description {_safe_strip(net.description)}"
            if net.notes:
                summary += f"; notes {_safe_strip(net.notes)}"
            lines.append(summary)
            if len(networks) == 20:
                lines.append("…showing latest 20 networks.")
            return "Tracked networks:\n" + "\n".join(lines)
        if cidr_match:
            return "I couldn't find that network in the database."
        return None

    ip_net = candidate.ip_network
    if not ip_net:
        return f"The network record '{candidate.name}' has an invalid CIDR ({candidate.cidr})."

    used_addresses = {host.ip_address for host in candidate.hosts if host.ip_address}
    reserved_addresses = {
        host.ip_address for host in candidate.hosts if host.ip_address and getattr(host, "is_reserved", False)
    }

    if any(token in lowered for token in ("list hosts", "show hosts", "all hosts", "hosts list", "detailed hosts", "host list")):
        return _format_network_hosts(candidate, message, lowered, user)

    requested_single = any(token in lowered for token in ("first", "single", "one"))
    limit = 1 if requested_single else 5
    available: List[str] = []
    for addr in ip_net.hosts():
        ip_str = str(addr)
        if ip_str in used_addresses:
            continue
        available.append(ip_str)
        if len(available) >= limit:
            break

    requested_pairs: List[Tuple[str, str]] = []
    host_count = len(candidate.hosts)

    def _add_pair(label: str, value: Optional[str]):
        requested_pairs.append((label, value or "n/a"))

    if "gateway" in lowered:
        _add_pair("Gateway", candidate.gateway)
    if "vlan" in lowered:
        _add_pair("VLAN", candidate.vlan)
    if any(term in lowered for term in ("site", "location")):
        _add_pair("Site", candidate.site)
    if "cidr" in lowered or "subnet" in lowered or "range" in lowered:
        _add_pair("CIDR", candidate.cidr)
    if "network address" in lowered or "network ip" in lowered or "base address" in lowered:
        _add_pair("Network", candidate.network_address)
    if "broadcast" in lowered:
        _add_pair("Broadcast", candidate.broadcast_address)
    if any(term in lowered for term in ("host count", "hosts count", "number of hosts", "host capacity")):
        _add_pair("Hosts tracked", str(host_count))
    if "description" in lowered:
        _add_pair("Description", _safe_strip(candidate.description))
    if "note" in lowered:
        _add_pair("Notes", _safe_strip(candidate.notes))
    if "reserved" in lowered:
        _add_pair("Reserved addresses tracked", str(len(reserved_addresses)))

    summary_lines = [f"Network {candidate.name} ({candidate.cidr})"]
    location_bits = []
    if candidate.site:
        location_bits.append(f"site {candidate.site}")
    if candidate.vlan:
        location_bits.append(f"VLAN {candidate.vlan}")
    if location_bits:
        summary_lines.append("; ".join(location_bits))
    if candidate.gateway:
        summary_lines.append(f"Gateway: {candidate.gateway}")
    summary_lines.append(f"Network: {candidate.network_address or 'n/a'}")
    summary_lines.append(f"Broadcast: {candidate.broadcast_address or 'n/a'}")
    if candidate.description:
        summary_lines.append(f"Description: {_safe_strip(candidate.description)}")
    if candidate.notes:
        summary_lines.append(f"Notes: {_safe_strip(candidate.notes)}")
    summary_lines.append(f"Assigned/reserved addresses tracked: {len(used_addresses)}")
    if reserved_addresses:
        preview = ", ".join(sorted(reserved_addresses)[:5])
        if len(reserved_addresses) > 5:
            preview += ", …"
        summary_lines.append(f"Reserved addresses: {preview}")

    if available:
        label = "Next available IP" if len(available) == 1 else "Next available IPs"
        summary_lines.append(f"{label}: {', '.join(available)}")
    else:
        summary_lines.append("No free addresses detected in this network.")

    if requested_pairs:
        detail_lines = [f"{candidate.name} ({candidate.cidr}) details:"]
        for label, value in requested_pairs:
            detail_lines.append(f"{label}: {value}")
        if "reserved" in lowered:
            detail_lines.append(f"Reserved addresses tracked: {len(reserved_addresses)}")
            if reserved_addresses:
                detail_lines.append("Reserved addresses: " + ", ".join(sorted(reserved_addresses)))
            else:
                detail_lines.append("No reserved addresses found in this network.")
        if "hosts" in lowered and not any(label.startswith("Hosts") for label, _ in requested_pairs):
            detail_lines.append(f"Hosts tracked: {host_count}")
        if available and any(term in lowered for term in ("available ip", "free ip", "next ip", "next available")):
            label = "Next available IP" if len(available) == 1 else "Next available IPs"
            detail_lines.append(f"{label}: {', '.join(available)}")
        return "\n".join(detail_lines)

    return "\n".join(summary_lines)


def _format_network_hosts(network: Network, message: str, lowered: str, user) -> str:
    hosts = list(network.hosts)
    if not hosts:
        return f"No hosts are registered under {network.name} ({network.cidr})."

    # Filter hosts by intent
    filters_applied: List[str] = []

    if "reserved" in lowered and "available" not in lowered:
        hosts = [h for h in hosts if h.is_reserved]
        filters_applied.append("reserved")
    elif "available" in lowered or "free" in lowered:
        hosts = [h for h in hosts if not h.is_reserved]
        filters_applied.append("available")

    user_tokens = _extract_user_tokens(message)
    if user_tokens:
        lowered_users = {token.lower() for token in user_tokens}
        hosts = [
            h for h in hosts if h.assigned_to and h.assigned_to.lower() in lowered_users
        ]
        filters_applied.append("assigned to specified user")
    elif any(term in lowered for term in ("assigned to me", "my hosts")) and user and getattr(user, "username", None):
        hosts = [h for h in hosts if h.assigned_to and h.assigned_to.lower() == user.username.lower()]
        filters_applied.append(f"assigned to {user.username}")

    host_tokens = _extract_network_host_tokens(message)
    if host_tokens:
        normalized_tokens = []
        for token in host_tokens:
            cleaned = _safe_strip(token, " \"'.,:;!")
            if cleaned:
                normalized_tokens.append(cleaned.lower())

        def matches_token(host: NetworkHost, token: str) -> bool:
            token_plain = token.replace(":", "").replace("-", "")
            mac_plain = (host.mac_address or "").replace(":", "").replace("-", "").lower()
            return any(
                (
                    host.ip_address and token in host.ip_address.lower(),
                    host.hostname and token in host.hostname.lower(),
                    mac_plain and token_plain in mac_plain,
                )
            )

        hosts = [h for h in hosts if any(matches_token(h, tok) for tok in normalized_tokens)]
        filters_applied.append("matching provided identifiers")

    device_match = re.search(r"(?:device|host)\\s+type\\s+([a-z0-9_.\\- ]+)", lowered)
    if device_match:
        device_value = _safe_strip(device_match.group(1))
        hosts = [
            h for h in hosts if h.device_type and device_value.lower() in h.device_type.lower()
        ]
        filters_applied.append(f"device type contains '{device_value}'")

    description_match = re.search(r"(?:notes?|description)\\s+(?:contains\\s+)?([a-z0-9_.\\- ]+)", lowered)
    if description_match:
        desc_value = _safe_strip(description_match.group(1))
        hosts = [
            h for h in hosts if h.description and desc_value.lower() in h.description.lower()
        ]
        filters_applied.append(f"description contains '{desc_value}'")

    if not hosts:
        filter_text = "; ".join(filters_applied) if filters_applied else "specified criteria"
        return f"No hosts matched {filter_text} under {network.name} ({network.cidr})."

    hosts = sorted(hosts, key=lambda h: (h.ip_address or "", h.hostname or ""))
    header = f"Hosts tracked for {network.name} ({network.cidr})"
    if filters_applied:
        header += f" — filters: {', '.join(filters_applied)}"
    lines = [header + ":"]
    for host in hosts[:25]:
        ip_addr = host.ip_address or "n/a"
        hostname = host.hostname or "—"
        mac = host.mac_address or "—"
        device_type = host.device_type or "—"
        assigned = host.assigned_to or "Unassigned"
        reserved = "Reserved" if host.is_reserved else "Available"
        description = host.description or "—"
        lines.append(
            f"{ip_addr} — hostname {hostname}; MAC {mac}; type {device_type}; assigned to {assigned}; "
            f"status {reserved}; description {description}"
        )
    if len(hosts) > 25:
        lines.append("…limited to first 25 hosts.")
    return "\n".join(lines)


def _answer_ticket_query(message: str, lowered: str, user) -> Optional[str]:
    id_match = TICKET_ID_PATTERN.search(message)
    if id_match:
        ticket_id = int(id_match.group(1))
        ticket = (
            Ticket.query.options(joinedload(Ticket.assignee))
            .filter(Ticket.id == ticket_id)
            .first()
        )
        if not ticket:
            return f"Ticket #{ticket_id} was not found."
        assignee = ticket.assignee.username if ticket.assignee else "Unassigned"
        created = ticket.created_at.strftime("%Y-%m-%d %H:%M") if ticket.created_at else "—"
        updated = ticket.updated_at.strftime("%Y-%m-%d %H:%M") if ticket.updated_at else "—"
        return (
            f"Ticket #{ticket.id}: {ticket.subject}\n"
            f"Status: {ticket.status or 'Unknown'} | Priority: {ticket.priority or 'n/a'} | Department: {ticket.department or 'n/a'}\n"
            f"Assigned to: {assignee} | Created: {created} | Updated: {updated}"
        )

    base_query = Ticket.query.options(joinedload(Ticket.assignee))
    filters: List[str] = []
    results: List[Ticket] = []
    total: Optional[int] = None

    if any(token in lowered for token in ("assigned to me", "my ticket", "my tickets")) and user:
        base_query = base_query.filter(Ticket.assigned_to == user.id)
        filters.append(f"assigned to {user.username}")
    else:
        assignee_match = USER_REF_PATTERN.search(message)
        if assignee_match:
            target = _resolve_user_reference(assignee_match.group(1))
            if target:
                base_query = base_query.filter(Ticket.assigned_to == target.id)
                filters.append(f"assigned to {target.username}")

    if "created by me" in lowered and user:
        base_query = base_query.filter(Ticket.created_by == user.id)
        filters.append("created by you")

    if "today" in lowered:
        today = date.today()
        if "updated" in lowered and "created" not in lowered:
            base_query = base_query.filter(func.date(Ticket.updated_at) == today)
            filters.append("updated today")
        else:
            base_query = base_query.filter(func.date(Ticket.created_at) == today)
            filters.append("created today")

    if "yesterday" in lowered:
        yesterday = date.today() - timedelta(days=1)
        base_query = base_query.filter(func.date(Ticket.created_at) == yesterday)
        filters.append("created yesterday")

    if any(token in lowered for token in ("open", "pending", "progress", "unresolved")):
        base_query = base_query.filter(func.lower(Ticket.status).in_(OPEN_STATUS_VALUES))
        filters.append("status in open set")
    elif any(token in lowered for token in ("closed", "resolved", "done", "completed", "cancelled")):
        base_query = base_query.filter(func.lower(Ticket.status).in_(CLOSED_STATUS_VALUES))
        filters.append("status closed")

    for level in PRIORITY_LEVELS:
        if f"{level} priority" in lowered or f"priority {level}" in lowered:
            base_query = base_query.filter(func.lower(Ticket.priority) == level)
            filters.append(f"priority {level}")
            break

    dept_match = re.search(r"department\s+([a-z0-9_\- ]+)", lowered)
    if dept_match:
        dept = _safe_strip(dept_match.group(1))
        base_query = base_query.filter(func.lower(Ticket.department) == dept.lower())
        filters.append(f"department {dept}")

    need_total = "how many" in lowered or "count" in lowered
    used_content_filters = False
    phrases = _extract_candidate_phrases(message)
    if phrases:
        used_content_filters = True
    for phrase in phrases:
        like = f"%{phrase}%"
        phrase_query = base_query.filter(
            or_(
                Ticket.subject.ilike(like),
                Ticket.description.ilike(like),
                Ticket.department.ilike(like),
            )
        )
        phrase_results = phrase_query.order_by(Ticket.created_at.desc()).limit(20).all()
        if phrase_results:
            results = phrase_results
            total = phrase_query.count() if need_total else len(results)
            break

    if not results:
        keywords = _extract_keywords(message, extra_stop=TICKET_KEYWORDS | TICKET_TEXT_STOP)
        if keywords:
            used_content_filters = True
        keyword_query = base_query
        for keyword in keywords[:4]:
            like = f"%{keyword}%"
            keyword_query = keyword_query.filter(
                or_(
                    Ticket.subject.ilike(like),
                    Ticket.description.ilike(like),
                    Ticket.department.ilike(like),
                )
            )
        results = keyword_query.order_by(Ticket.created_at.desc()).limit(20).all()
        if results:
            total = keyword_query.count() if need_total else len(results)

    if not results:
        if filters or used_content_filters:
            return "No tickets matched those filters."
        fallback_query = base_query.order_by(Ticket.created_at.desc())
        results = fallback_query.limit(20).all()
        total = fallback_query.count() if need_total else len(results)

    if not results:
        if filters:
            return "No tickets matched those filters."
        return None

    lines = []
    for ticket in results:
        assignee = ticket.assignee.username if ticket.assignee else "Unassigned"
        created = ticket.created_at.strftime("%Y-%m-%d") if ticket.created_at else "—"
        line = (
            f"#{ticket.id} {ticket.subject} — {ticket.status or 'Unknown'}"
            f" | Priority {ticket.priority or 'n/a'} | Assigned to {assignee} | Created {created}"
        )
        lines.append(line)

    if total > len(results):
        lines.append(f"…and {total - len(results)} more matching tickets.")

    if filters:
        filter_text = ", ".join(filters)
        header = f"Found {total} ticket(s) ({filter_text})."
    else:
        header = f"Found {total} ticket(s)."

    return "\n".join([header] + lines)


def _answer_knowledge_query(message: str) -> Optional[str]:
    keywords = _extract_keywords(message)
    if not keywords:
        return None

    query = (
        KnowledgeArticle.query.outerjoin(
            KnowledgeAttachment,
            KnowledgeAttachment.article_id == KnowledgeArticle.id,
        )
        .options(joinedload(KnowledgeArticle.attachments))
        .filter(KnowledgeArticle.is_published.is_(True))
        .distinct()
    )

    conditions = []
    for keyword in keywords[:6]:
        like = f"%{keyword}%"
        conditions.extend(
            [
                KnowledgeArticle.title.ilike(like),
                KnowledgeArticle.summary.ilike(like),
                KnowledgeArticle.tags.ilike(like),
                KnowledgeArticle.content.ilike(like),
                KnowledgeAttachment.original_filename.ilike(like),
                KnowledgeAttachment.extracted_text.ilike(like),
            ]
        )

    if conditions:
        query = query.filter(or_(*conditions))

    results = query.order_by(KnowledgeArticle.updated_at.desc()).limit(10).all()
    if not results:
        return None

    lines = []
    for article in results:
        updated = article.updated_at.strftime("%Y-%m-%d") if article.updated_at else "—"
        tags = article.tags or "n/a"
        attachment_count = len(article.attachments)
        attachment_part = f" | attachments: {attachment_count}" if attachment_count else ""
        try:
            link = url_for("knowledge.view_article", article_id=article.id, _external=True)
        except RuntimeError:
            link = ""
        link_part = f" | link: <{link}>" if link else ""
        lines.append(
            f"#{article.id} {article.title} — tags: {tags}; updated {updated}{attachment_part}{link_part}"
        )

    return "Top knowledge base matches:\n" + "\n".join(lines)


def _answer_hardware_query(message: str, lowered: str, user) -> Optional[str]:
    specific = _lookup_hardware_asset_by_identifier(message)
    if specific:
        return _format_hardware_detail(specific)

    base_query = HardwareAsset.query.options(joinedload(HardwareAsset.assignee))
    filters: List[str] = []

    if any(token in lowered for token in ("assigned to me", "my devices", "my hardware", "my laptop")) and user:
        base_query = base_query.filter(HardwareAsset.assigned_to == user.id)
        filters.append(f"assigned to {user.username}")
    else:
        assignee_match = USER_REF_PATTERN.search(message)
        if assignee_match:
            target = _resolve_user_reference(assignee_match.group(1))
            if target:
                base_query = base_query.filter(HardwareAsset.assigned_to == target.id)
                filters.append(f"assigned to {target.username}")

    if "unassigned" in lowered or "available" in lowered:
        base_query = base_query.filter(HardwareAsset.assigned_to.is_(None))
        filters.append("unassigned")

    loc_match = re.search(r"location\s+([a-z0-9_\- ]+)", lowered)
    if loc_match:
        location = _safe_strip(loc_match.group(1))
        base_query = base_query.filter(func.lower(HardwareAsset.location) == location.lower())
        filters.append(f"location {location}")

    keywords = _extract_keywords(message, extra_stop={"hardware", "device", "devices", "asset", "assets"})
    need_total = "how many" in lowered or "count" in lowered
    request_all = any(
        phrase in lowered
        for phrase in (
            "all hardware",
            "list hardware",
            "show hardware",
            "hardware inventory",
            "όλο το υλικό",
            "λίστα υλικού",
        )
    ) or lowered.strip() in {"list all hardware", "list hardware", "show all hardware", "display hardware"}

    results: List[HardwareAsset] = []

    if request_all and not keywords and not filters:
        results = base_query.order_by(HardwareAsset.updated_at.desc()).limit(20).all()
        total = base_query.count() if need_total else len(results)
    else:
        phrases = _extract_candidate_phrases(message)
        for phrase in phrases:
            like = f"%{phrase}%"
            phrase_results = (
                base_query.filter(
                    or_(
                        HardwareAsset.category.ilike(like),
                        HardwareAsset.type.ilike(like),
                        HardwareAsset.manufacturer.ilike(like),
                        HardwareAsset.model.ilike(like),
                        HardwareAsset.hostname.ilike(like),
                        HardwareAsset.asset_tag.ilike(like),
                        HardwareAsset.serial_number.ilike(like),
                        HardwareAsset.custom_tag.ilike(like),
                    )
                )
                .order_by(HardwareAsset.updated_at.desc())
                .limit(10)
                .all()
            )
            if phrase_results:
                results = phrase_results
                break

    if not results:
        keyword_conditions = []
        for keyword in keywords[:6]:
            like = f"%{keyword}%"
            keyword_conditions.append(
                or_(
                    HardwareAsset.category.ilike(like),
                    HardwareAsset.type.ilike(like),
                    HardwareAsset.manufacturer.ilike(like),
                    HardwareAsset.model.ilike(like),
                    HardwareAsset.hostname.ilike(like),
                    HardwareAsset.asset_tag.ilike(like),
                    HardwareAsset.serial_number.ilike(like),
                    HardwareAsset.custom_tag.ilike(like),
                )
            )

        filtered_query = base_query.filter(or_(*keyword_conditions)) if keyword_conditions else base_query
        results = filtered_query.order_by(HardwareAsset.updated_at.desc()).limit(10).all()
        total = filtered_query.count() if need_total else len(results)
    elif not (request_all and not keywords and not filters):
        total = len(results)

    if not results:
        if request_all and not keywords and not filters:
            fallback_query = HardwareAsset.query.order_by(HardwareAsset.updated_at.desc())
            fallback_results = fallback_query.limit(20).all()
            if fallback_results:
                results = fallback_results
                total = fallback_query.count() if need_total else len(results)

    if not results:
        if filters or keywords or request_all:
            return "No hardware assets matched those filters."
        return None

    lines = []
    for asset in results:
        name = asset.asset_tag or asset.custom_tag or asset.hostname or f"Asset #{asset.id}"
        category = asset.category or asset.type or "hardware"
        status = asset.status or "unknown"
        assignee = asset.assignee.username if asset.assignee else "Unassigned"
        location = asset.location or "n/a"
        line = (
            f"{name} — {category}; status {status}; assigned to {assignee}; location {location}"
        )
        lines.append(line)

    if total > len(results):
        lines.append(f"…and {total - len(results)} more matching assets.")

    if filters:
        header = f"Found {total} hardware asset(s) ({', '.join(filters)})."
    else:
        header = f"Found {total} hardware asset(s)."

    return "\n".join([header] + lines)


def _answer_software_query(message: str, lowered: str, user) -> Optional[str]:
    current_app.logger.info("Assistant software query message=%s", message)
    specific = _lookup_software_asset_by_identifier(message)
    if specific:
        current_app.logger.info("Assistant software query matched specific asset id=%s", specific.id)
        return _format_software_detail(specific)

    base_query = SoftwareAsset.query.options(joinedload(SoftwareAsset.assignee))
    filters: List[str] = []
    keywords = _extract_keywords(message, extra_stop={"software", "license", "licence", "application", "app", "subscription"})
    need_total = "how many" in lowered or "count" in lowered
    request_all = any(
        phrase in lowered
        for phrase in (
            "all software",
            "list software",
            "show software",
            "software inventory",
            "όλο το λογισμικό",
            "λίστα λογισμικού",
        )
    ) or lowered.strip() in {"list all software", "list software", "show all software", "display software"}
    field_filters_applied = False

    category_match = re.search(r"category\s+(?:is|=)?\s*['\"]?([a-z0-9\-\s_/]+)['\"]?", message, flags=re.IGNORECASE)
    if category_match:
        category_value = _safe_strip(category_match.group(1))
        if category_value:
            base_query = base_query.filter(func.lower(SoftwareAsset.category) == category_value.lower())
            filters.append(f"category {category_value}")
            field_filters_applied = True

    vendor_match = re.search(r"vendor\s+(?:is|=)?\s*['\"]?([a-z0-9\-\s_/]+)['\"]?", message, flags=re.IGNORECASE)
    if vendor_match:
        vendor_value = _safe_strip(vendor_match.group(1))
        if vendor_value:
            base_query = base_query.filter(func.lower(SoftwareAsset.vendor) == vendor_value.lower())
            filters.append(f"vendor {vendor_value}")
            field_filters_applied = True

    if any(token in lowered for token in ("assigned to me", "my software", "my license", "my licences")) and user:
        base_query = base_query.filter(SoftwareAsset.assigned_to == user.id)
        filters.append(f"assigned to {user.username}")
        field_filters_applied = True
    else:
        assignee_match = USER_REF_PATTERN.search(message)
        if assignee_match:
            target = _resolve_user_reference(assignee_match.group(1))
            if target:
                base_query = base_query.filter(SoftwareAsset.assigned_to == target.id)
                filters.append(f"assigned to {target.username}")
                field_filters_applied = True

    if "unassigned" in lowered or "available" in lowered:
        base_query = base_query.filter(SoftwareAsset.assigned_to.is_(None))
        filters.append("unassigned")
        field_filters_applied = True

    if "expir" in lowered:
        today = date.today()
        window = today + timedelta(days=60)
        base_query = base_query.filter(
            SoftwareAsset.expiration_date.isnot(None),
            SoftwareAsset.expiration_date <= window,
        )
        filters.append("expiring within 60 days")

    results: List[SoftwareAsset] = []
    if request_all and not field_filters_applied:
        results = base_query.order_by(SoftwareAsset.updated_at.desc()).limit(20).all()
        total = base_query.count() if need_total else len(results)
        current_app.logger.info("Assistant software query request_all fetched=%s total=%s", len(results), total)
    else:
        phrases = _extract_candidate_phrases(message)
        for phrase in phrases:
            like = f"%{phrase}%"
            name_results = (
                base_query.filter(
                    or_(
                        SoftwareAsset.name.ilike(like),
                        SoftwareAsset.custom_tag.ilike(like),
                    )
                )
                .order_by(SoftwareAsset.updated_at.desc())
                .limit(10)
                .all()
            )
            if name_results:
                results = name_results
                current_app.logger.info("Assistant software query phrase matched by name/custom_tag phrase=%s count=%s", phrase, len(results))
                break

            phrase_results = (
                base_query.filter(
                    or_(*[column.ilike(like) for column in SOFTWARE_SEARCH_COLUMNS])
                )
                .order_by(SoftwareAsset.updated_at.desc())
                .limit(10)
                .all()
            )
            if phrase_results:
                results = phrase_results
                current_app.logger.info("Assistant software query phrase matched by broad search phrase=%s count=%s", phrase, len(results))
                break

    if not results:
        keyword_conditions = []
        for keyword in keywords[:6]:
            like = f"%{keyword}%"
            keyword_conditions.append(or_(*[column.ilike(like) for column in SOFTWARE_SEARCH_COLUMNS]))

        filtered_query = base_query.filter(and_(*keyword_conditions)) if keyword_conditions else base_query
        results = filtered_query.order_by(SoftwareAsset.updated_at.desc()).limit(10).all()
        total = filtered_query.count() if need_total else len(results)
    elif not (request_all and not field_filters_applied):
        total = len(results)

    if not results:
        if field_filters_applied:
            fallback_query = base_query.order_by(SoftwareAsset.updated_at.desc())
            fallback_results = fallback_query.limit(20).all()
            if fallback_results:
                current_app.logger.info("Assistant software query fallback (field filters) returned %s records", len(fallback_results))
                results = fallback_results
                total = fallback_query.count() if need_total else len(results)
        elif request_all or (not field_filters_applied and not keywords):
            fallback_query = SoftwareAsset.query.order_by(SoftwareAsset.updated_at.desc())
            fallback_results = fallback_query.limit(20 if request_all else 10).all()
            if fallback_results:
                current_app.logger.info("Assistant software query fallback (global) returned %s records", len(fallback_results))
                results = fallback_results
                total = fallback_query.count() if need_total else len(results)

    if not results:
        current_app.logger.info("Assistant software query empty after fallbacks.")
        if filters or keywords or request_all:
            return "No software assets matched those filters."
        return None

    lines = []
    for asset in results:
        name = asset.name or f"Software #{asset.id}"
        version = asset.version or "—"
        vendor = asset.vendor or "Unknown vendor"
        assignee = asset.assignee.username if asset.assignee else "Unassigned"
        expires = asset.expiration_date.strftime("%Y-%m-%d") if asset.expiration_date else "n/a"
        license_key = asset.license_key or "n/a"
        serial = asset.serial_number or "n/a"
        line = (
            f"{name} {version} — {vendor}; license type {asset.license_type or 'n/a'}; license key {license_key}; serial {serial}; assigned to {assignee}; expires {expires}"
        )
        lines.append(line)

    if total > len(results):
        lines.append(f"…and {total - len(results)} more matching licenses.")

    if filters:
        header = f"Found {total} software record(s) ({', '.join(filters)})."
    else:
        header = f"Found {total} software record(s)."

    current_app.logger.info("Assistant software query returning %s rows", len(results))
    return "\n".join([header] + lines)


def _extract_keywords(text: str, extra_stop: Optional[Iterable[str]] = None) -> List[str]:
    stops = set(STOP_WORDS)
    if extra_stop:
        stops.update(extra_stop)
    words = re.findall(r"[a-z0-9]{3,}", text.lower())
    return [word for word in words if word not in stops]


def _resolve_user_reference(identifier: str) -> Optional[User]:
    cleaned = _safe_strip(identifier).strip(".,:;!")
    if not cleaned:
        return None
    return User.query.filter(func.lower(User.username) == cleaned.lower()).first()


def _extract_candidate_phrases(message: str) -> List[str]:
    candidates: List[str] = []

    # quoted phrases take priority
    for match in QUOTED_PATTERN.finditer(message):
        phrase = _safe_strip(match.group(1) or match.group(2))
        if phrase:
            candidates.append(phrase)

    # phrases introduced by keywords (for, find, etc.)
    for match in PHRASE_PATTERN.finditer(message):
        raw = match.group(1) or ""
        phrase = _safe_strip(raw)
        if not phrase:
            continue
        phrase = re.split(r"[?.,;]", phrase)[0]
        phrase = re.sub(r"\b(key|keys|license|licence|serial|product key)\b", "", phrase, flags=re.IGNORECASE)
        phrase = _safe_strip(re.sub(r"\s+", " ", phrase))
        if phrase and phrase.lower() not in (cand.lower() for cand in candidates):
            candidates.append(phrase)

    return candidates[:3]


def _extract_user_tokens(message: str) -> List[str]:
    tokens: List[str] = []

    for match in USER_REF_PATTERN.finditer(message):
        candidate = _safe_strip(match.group(1), " \"'.,:;!")
        if candidate:
            tokens.append(candidate)

    for match in QUOTED_PATTERN.finditer(message):
        candidate = _safe_strip(match.group(1) or match.group(2))
        if candidate:
            tokens.append(candidate)

    seen = set()
    deduped: List[str] = []
    for token in tokens:
        key = token.lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(token)
    return deduped


def _extract_network_host_tokens(message: str) -> List[str]:
    tokens: List[str] = []

    for match in HOSTNAME_QUERY_PATTERN.finditer(message):
        candidate = _safe_strip(match.group(1))
        if candidate:
            tokens.append(candidate)

    for match in MAC_QUERY_PATTERN.finditer(message):
        candidate = _safe_strip(match.group(1))
        if candidate:
            tokens.append(candidate)

    for match in IP_ADDRESS_PATTERN.finditer(message):
        candidate = _safe_strip(match.group(0))
        if candidate and "/" not in candidate:  # avoid double-counting CIDRs
            tokens.append(candidate)

    return tokens


def _normalize_network_name_hint(raw: str) -> str:
    text = _safe_strip(raw)
    if not text:
        return ""
    breaker = NETWORK_HINT_BREAK_RE.search(text)

    def _tokenize(segment: str) -> List[str]:
        cleaned = re.sub(r"[^\w\s\-.:/]", " ", segment)
        return [word for word in re.split(r"\s+", cleaned) if word and word.lower() not in NETWORK_HINT_STOPWORDS]

    if breaker:
        before = text[: breaker.start()]
        after = text[breaker.end() :]
        after_tokens = _tokenize(after)
        before_tokens = _tokenize(before)
        if after_tokens:
            words = after_tokens
        elif before_tokens:
            words = before_tokens
        else:
            words = _tokenize(text)
    else:
        words = _tokenize(text)

    if not words:
        return ""
    cleaned = re.sub(r"\s+", " ", " ".join(words[:6])).strip(" -_/")
    return cleaned


def _canonicalize_cidr(value: str) -> str:
    try:
        return str(ipaddress.ip_network(value, strict=False))
    except ValueError:
        return (value or "").strip().lower()


def _find_network_by_cidr(networks: Iterable[Network], cidr_value: str) -> Optional[Network]:
    canonical = _canonicalize_cidr(cidr_value)
    for net in networks:
        if _canonicalize_cidr(net.cidr or "") == canonical:
            return net
    for net in networks:
        if canonical in (net.cidr or "").lower():
            return net
    return None


def _normalize_label(value: str) -> str:
    if not value:
        return ""
    cleaned = re.sub(r"[^a-z0-9]+", " ", value.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _match_network_by_normalized(networks: Iterable[Network], normalized: str) -> Optional[Network]:
    if not normalized:
        return None

    lowered = normalized.lower().strip()
    variations = {lowered}
    if not lowered.endswith(" network"):
        variations.add(f"{lowered} network")
    if not lowered.endswith(" subnet"):
        variations.add(f"{lowered} subnet")
    if not lowered.endswith(" vlan"):
        variations.add(f"{lowered} vlan")

    for value in variations:
        for net in networks:
            if _normalize_label(net.name) == _normalize_label(value):
                return net
            if (net.name or "").strip().lower() == value:
                return net

    tokens = [token for token in re.split(r"\s+", normalized) if token]
    if tokens:
        best_match: Optional[Tuple[int, Network]] = None
        for net in networks:
            name_norm = _normalize_label(net.name)
            token_hits = sum(1 for token in tokens if token in name_norm)
            if token_hits <= 0:
                continue
            if not best_match or token_hits > best_match[0]:
                best_match = (token_hits, net)
        if best_match:
            return best_match[1]

    lowered_norm = _normalize_label(normalized)
    for net in networks:
        for field in (net.site, net.vlan, net.description, net.notes):
            if lowered_norm and lowered_norm in _normalize_label(field or ""):
                return net

    for net in networks:
        name_lower = (net.name or "").lower()
        if lowered in name_lower:
            return net

    return None


def _lookup_hardware_asset_by_identifier(message: str) -> Optional[HardwareAsset]:
    query = HardwareAsset.query.options(joinedload(HardwareAsset.assignee))

    for pattern, column in (
        (ASSET_TAG_PATTERN, HardwareAsset.asset_tag),
        (HOSTNAME_PATTERN, HardwareAsset.hostname),
        (SERIAL_PATTERN, HardwareAsset.serial_number),
    ):
        match = pattern.search(message)
        if match:
            value = _safe_strip(match.group(1))
            if value:
                asset = query.filter(func.lower(column) == value.lower()).first()
                if asset:
                    return asset

    return None


def _lookup_software_asset_by_identifier(message: str) -> Optional[SoftwareAsset]:
    query = SoftwareAsset.query.options(joinedload(SoftwareAsset.assignee))

    candidates: List[Tuple[str, Any]] = []

    for match in SOFTWARE_TAG_PATTERN.finditer(message):
        raw = match.group(1)
        value = _safe_strip(raw)
        if value:
            candidates.append((value, SoftwareAsset.custom_tag))

    direct_patterns = (
        (
            re.compile(
                r"license\s+(?:key|code|number|id)\s*[:#]?\s*([a-z0-9\-]{4,})",
                re.IGNORECASE,
            ),
            SoftwareAsset.license_key,
        ),
        (
            re.compile(
                r"activation\s+(?:code|key)\s*[:#]?\s*([a-z0-9\-]{4,})",
                re.IGNORECASE,
            ),
            SoftwareAsset.license_key,
        ),
        (
            re.compile(
                r"seria\w*\s+(?:number|no\.?)\s*[:#]?\s*([a-z0-9_.\-]+)",
                re.IGNORECASE,
            ),
            SoftwareAsset.serial_number,
        ),
        (
            re.compile(
                r"serial\s*#\s*([a-z0-9_.\-]+)",
                re.IGNORECASE,
            ),
            SoftwareAsset.serial_number,
        ),
    )

    for pattern, column in direct_patterns:
        for match in pattern.finditer(message):
            raw = match.group(1)
            cleaned = _safe_strip(raw)
            value = cleaned.strip(" '\"#:;,") if cleaned else ""
            if value:
                candidates.append((value, column))

    bare_license_pattern = re.compile(r"\b(?:[a-z0-9]{4,}-){2,}[a-z0-9]{4,}\b", re.IGNORECASE)
    for match in bare_license_pattern.finditer(message):
        raw = match.group(0)
        cleaned = _safe_strip(raw)
        value = cleaned.strip(" '\"#:;,") if cleaned else ""
        if value:
            candidates.append((value, SoftwareAsset.license_key))

    seen: set[str] = set()
    for value, column in candidates:
        lowered = value.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        asset = query.filter(func.lower(column) == lowered).first()
        if asset:
            return asset

    return None


def _format_hardware_detail(asset: HardwareAsset) -> str:
    assignee = asset.assignee.username if asset.assignee else "Unassigned"
    created = asset.created_at.strftime("%Y-%m-%d") if asset.created_at else "—"
    updated = asset.updated_at.strftime("%Y-%m-%d") if asset.updated_at else "—"
    return (
        f"Hardware asset {asset.asset_tag or asset.custom_tag or asset.hostname or '#' + str(asset.id)}\n"
        f"Category: {asset.category or asset.type or 'n/a'} | Manufacturer: {asset.manufacturer or 'n/a'} | Model: {asset.model or 'n/a'}\n"
        f"Assigned to: {assignee} | Location: {asset.location or 'n/a'}\n"
        f"Status: {asset.status or 'n/a'} | Created: {created} | Updated: {updated}"
    )


def _format_software_detail(asset: SoftwareAsset) -> str:
    assignee = asset.assignee.username if asset.assignee else "Unassigned"
    expires = asset.expiration_date.strftime("%Y-%m-%d") if asset.expiration_date else "n/a"
    renewed = asset.renewal_date.strftime("%Y-%m-%d") if asset.renewal_date else "n/a"
    license_key = asset.license_key or "n/a"
    return (
        f"Software asset {asset.name or asset.custom_tag or '#' + str(asset.id)}\n"
        f"Version: {asset.version or 'n/a'} | Vendor: {asset.vendor or 'n/a'} | License type: {asset.license_type or 'n/a'}\n"
        f"License key: {license_key}\n"
        f"Assigned to: {assignee} | Expires: {expires} | Renewal date: {renewed}"
    )
