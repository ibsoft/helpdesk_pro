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
from datetime import date, timedelta
from typing import List, Dict, Any, Iterable, Optional

import requests
from flask import Blueprint, jsonify, request, abort
from flask_login import login_required, current_user
from flask_babel import gettext as _
from sqlalchemy import func, or_
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
    User,
)
from app.models.assistant import DEFAULT_SYSTEM_PROMPT
from app.navigation import is_feature_allowed


CIDR_PATTERN = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}/\d{1,2}\b")
TICKET_ID_PATTERN = re.compile(r"ticket\s+#?(\d+)|αιτημ(?:α|ατος)?\s*#?(\d+)", re.IGNORECASE)
USER_REF_PATTERN = re.compile(r"(?:assigned to|for|owner|για|σε)\s+([a-z0-9_.\-άέήίόύώ]+)", re.IGNORECASE)
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
    "info",
    "information",
    "details",
    "lookup",
    "find",
    "me",
    "my",
    "latest",
}

OPEN_STATUS_VALUES = ["open", "in progress", "pending", "new", "reopened"]
CLOSED_STATUS_VALUES = ["closed", "resolved", "completed", "cancelled", "done"]
PRIORITY_LEVELS = ["critical", "urgent", "high", "medium", "low"]

TICKET_KEYWORDS = {
    "ticket", "tickets", "incident", "case", "request",
    "αίτημα", "αιτήματα", "εισιτήριο", "εισιτήρια", "υπόθεση"
}
KNOWLEDGE_KEYWORDS = {
    "knowledge", "kb", "article", "articles", "procedure", "guide", "manual", "attachment", "attachments",
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
    "δίκτυο", "υποδίκτυο", "cidr", "vlan", "ip", "ίπ", "δικτυο"
}

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

    system_prompt = config.system_prompt or DEFAULT_SYSTEM_PROMPT
    history.append({"role": "user", "content": message})
    messages_for_model = [{"role": "system", "content": system_prompt}] + history if system_prompt else history

    try:
        if config.provider == "chatgpt":
            if not config.openai_api_key:
                return jsonify({"success": False, "message": _("OpenAI API key is not configured.")}), 400
            reply = _call_openai(messages_for_model, config, allow_tools=False)
        elif config.provider == "chatgpt_hybrid":
            if not config.openai_api_key:
                return jsonify({"success": False, "message": _("OpenAI API key is not configured.")}), 400
            tool_context = {
                "user": current_user,
                "history": history,
                "latest_user_message": message,
            }
            reply = _call_openai(messages_for_model, config, allow_tools=True, tool_context=tool_context)
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
                    "name": "query_helpdesk_modules",
                    "description": (
                        "Look up information from the Helpdesk Pro PostgreSQL database. "
                        "Use this when you need live data about tickets, knowledge base articles, "
                        "hardware/software inventory, or network allocations."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": (
                                    "Natural language description of what to retrieve, including any filters "
                                    "(ticket ids, usernames, asset tags, networks, etc.)."
                                ),
                            }
                        },
                        "required": ["query"],
                    },
                },
            }
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
        if depth >= 3:
            return message.get("content", "Tool call limit reached.").strip()
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
    return message.get("content", "").strip()


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
        return reply.strip()
    raise RuntimeError(_("Webhook response is missing a 'reply' field."))


def _execute_tool_call(tool_call: Dict[str, Any], context: Dict[str, Any]) -> str:
    function = tool_call.get("function") or {}
    name = function.get("name") or ""
    if name != "query_helpdesk_modules":
        return f"Unsupported tool call: {name}"

    raw_args = function.get("arguments") or ""
    if isinstance(raw_args, dict):
        args = raw_args
    else:
        try:
            args = json.loads(raw_args) if raw_args else {}
        except (ValueError, TypeError):
            args = {"query": raw_args if isinstance(raw_args, str) else ""}

    query = args.get("query") or context.get("latest_user_message") or ""
    history = context.get("history") or []
    user = context.get("user")

    if not query.strip():
        return "No query provided for helpdesk lookup."

    try:
        result = _call_builtin(query, history, user)
    except Exception as exc:
        return f"Error while querying database: {exc}"
    return result or "No matching records were found."


def _call_builtin(message: str, history: List[Dict[str, str]], user) -> str:
    """Answer simple operational questions by querying the local database."""

    lowered = message.lower()

    network_response = _answer_network_query(message, lowered)
    if network_response:
        return network_response

    if any(keyword in lowered for keyword in TICKET_KEYWORDS):
        ticket_response = _answer_ticket_query(message, lowered, user)
        if ticket_response:
            return ticket_response

    if any(keyword in lowered for keyword in KNOWLEDGE_KEYWORDS):
        knowledge_response = _answer_knowledge_query(message)
        if knowledge_response:
            return knowledge_response

    if any(keyword in lowered for keyword in HARDWARE_KEYWORDS):
        hardware_response = _answer_hardware_query(message, lowered, user)
        if hardware_response:
            return hardware_response

    if any(keyword in lowered for keyword in SOFTWARE_KEYWORDS):
        software_response = _answer_software_query(message, lowered, user)
        if software_response:
            return software_response

    return (
        "I can help with ticket summaries, knowledge base articles and attachments, inventory assignments, "
        "and network availability. For example: 'Show my open tickets today', 'Which articles mention VPN', "
        "'List hardware assigned to Alice', or 'Find an available IP in 192.168.1.0/24'."
    )


def _answer_network_query(message: str, lowered: str) -> Optional[str]:
    candidate = None
    cidr_match = CIDR_PATTERN.search(message)
    query = Network.query.options(joinedload(Network.hosts))

    if cidr_match:
        candidate = query.filter(func.lower(Network.cidr) == cidr_match.group(0).lower()).first()

    if not candidate:
        name_match = re.search(r"(?:network|subnet|vlan)\s+([a-z0-9_.\-\s]+)", lowered)
        if name_match:
            name = name_match.group(1).strip()
            candidate = query.filter(func.lower(Network.name) == name.lower()).first()
            if not candidate:
                candidate = query.filter(Network.name.ilike(f"%{name}%")).first()

    if not candidate:
        if cidr_match or any(term in lowered for term in NETWORK_KEYWORDS):
            return "I couldn't find that network in the database."
        return None

    ip_net = candidate.ip_network
    if not ip_net:
        return f"The network record '{candidate.name}' has an invalid CIDR ({candidate.cidr})."

    used_addresses = {host.ip_address for host in candidate.hosts if host.ip_address}
    reserved_addresses = {
        host.ip_address for host in candidate.hosts if host.ip_address and getattr(host, "is_reserved", False)
    }

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

    summary_lines = [f"Network {candidate.name} ({candidate.cidr})"]
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

    return "\n".join(summary_lines)


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
        dept = dept_match.group(1).strip()
        base_query = base_query.filter(func.lower(Ticket.department) == dept.lower())
        filters.append(f"department {dept}")

    need_total = "how many" in lowered or "count" in lowered
    total = base_query.count() if need_total else None
    results = base_query.order_by(Ticket.created_at.desc()).limit(20).all()
    if total is None:
        total = len(results)

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
        lines.append(
            f"#{article.id} {article.title} — tags: {tags}; updated {updated}{attachment_part}"
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
        location = loc_match.group(1).strip()
        base_query = base_query.filter(func.lower(HardwareAsset.location) == location.lower())
        filters.append(f"location {location}")

    keywords = _extract_keywords(message, extra_stop={"hardware", "device", "devices", "asset", "assets"})
    results: List[HardwareAsset] = []

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
        total = filtered_query.count() if "how many" in lowered or "count" in lowered else len(results)
    else:
        total = len(results)

    if not results:
        knowledge_hint = _answer_knowledge_query(message)
        if knowledge_hint:
            return (
                "No hardware assets matched those filters. However, I found related knowledge base items:\n"
                f"{knowledge_hint}"
            )
        if filters or keywords:
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
    specific = _lookup_software_asset_by_identifier(message)
    if specific:
        return _format_software_detail(specific)

    base_query = SoftwareAsset.query.options(joinedload(SoftwareAsset.assignee))
    filters: List[str] = []
    keywords = _extract_keywords(message, extra_stop={"software", "license", "licence", "application", "app", "subscription"})

    if any(token in lowered for token in ("assigned to me", "my software", "my license", "my licences")) and user:
        base_query = base_query.filter(SoftwareAsset.assigned_to == user.id)
        filters.append(f"assigned to {user.username}")
    else:
        assignee_match = USER_REF_PATTERN.search(message)
        if assignee_match:
            target = _resolve_user_reference(assignee_match.group(1))
            if target:
                base_query = base_query.filter(SoftwareAsset.assigned_to == target.id)
                filters.append(f"assigned to {target.username}")

    if "unassigned" in lowered or "available" in lowered:
        base_query = base_query.filter(SoftwareAsset.assigned_to.is_(None))
        filters.append("unassigned")

    if "expir" in lowered:
        today = date.today()
        window = today + timedelta(days=60)
        base_query = base_query.filter(
            SoftwareAsset.expiration_date.isnot(None),
            SoftwareAsset.expiration_date <= window,
        )
        filters.append("expiring within 60 days")

    results: List[SoftwareAsset] = []
    phrases = _extract_candidate_phrases(message)
    for phrase in phrases:
        like = f"%{phrase}%"
        phrase_results = (
            base_query.filter(
                or_(
                    SoftwareAsset.name.ilike(like),
                    SoftwareAsset.vendor.ilike(like),
                    SoftwareAsset.category.ilike(like),
                    SoftwareAsset.custom_tag.ilike(like),
                    SoftwareAsset.version.ilike(like),
                    SoftwareAsset.license_key.ilike(like),
                )
            )
            .order_by(SoftwareAsset.updated_at.desc())
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
                    SoftwareAsset.name.ilike(like),
                    SoftwareAsset.vendor.ilike(like),
                    SoftwareAsset.category.ilike(like),
                    SoftwareAsset.custom_tag.ilike(like),
                    SoftwareAsset.license_key.ilike(like),
                    SoftwareAsset.serial_number.ilike(like),
                    SoftwareAsset.version.ilike(like),
                )
            )

        filtered_query = base_query.filter(or_(*keyword_conditions)) if keyword_conditions else base_query
        results = filtered_query.order_by(SoftwareAsset.updated_at.desc()).limit(10).all()
        total = filtered_query.count() if "how many" in lowered or "count" in lowered else len(results)
    else:
        total = len(results)

    if not results:
        knowledge_hint = _answer_knowledge_query(message)
        if knowledge_hint:
            return (
                "No software assets matched those filters. However, I found related knowledge base items:\n"
                f"{knowledge_hint}"
            )
        if filters or keywords:
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

    return "\n".join([header] + lines)


def _extract_keywords(text: str, extra_stop: Optional[Iterable[str]] = None) -> List[str]:
    stops = set(STOP_WORDS)
    if extra_stop:
        stops.update(extra_stop)
    words = re.findall(r"[a-z0-9]{3,}", text.lower())
    return [word for word in words if word not in stops]


def _resolve_user_reference(identifier: str) -> Optional[User]:
    cleaned = (identifier or "").strip().strip(".,:;!")
    if not cleaned:
        return None
    return User.query.filter(func.lower(User.username) == cleaned.lower()).first()


def _extract_candidate_phrases(message: str) -> List[str]:
    candidates: List[str] = []

    # quoted phrases take priority
    for match in QUOTED_PATTERN.finditer(message):
        phrase = match.group(1) or match.group(2)
        if phrase:
            candidates.append(phrase.strip())

    # phrases introduced by keywords (for, find, etc.)
    for match in PHRASE_PATTERN.finditer(message):
        phrase = match.group(1).strip()
        if not phrase:
            continue
        phrase = re.split(r"[?.,;]", phrase)[0]
        phrase = re.sub(r"\b(key|keys|license|licence|serial|product key)\b", "", phrase, flags=re.IGNORECASE)
        phrase = re.sub(r"\s+", " ", phrase).strip()
        if phrase and phrase.lower() not in (cand.lower() for cand in candidates):
            candidates.append(phrase)

    return candidates[:3]


def _lookup_hardware_asset_by_identifier(message: str) -> Optional[HardwareAsset]:
    query = HardwareAsset.query.options(joinedload(HardwareAsset.assignee))

    for pattern, column in (
        (ASSET_TAG_PATTERN, HardwareAsset.asset_tag),
        (HOSTNAME_PATTERN, HardwareAsset.hostname),
        (SERIAL_PATTERN, HardwareAsset.serial_number),
    ):
        match = pattern.search(message)
        if match:
            value = match.group(1).strip()
            if value:
                asset = query.filter(func.lower(column) == value.lower()).first()
                if asset:
                    return asset

    return None


def _lookup_software_asset_by_identifier(message: str) -> Optional[SoftwareAsset]:
    query = SoftwareAsset.query.options(joinedload(SoftwareAsset.assignee))

    match = SOFTWARE_TAG_PATTERN.search(message)
    if match:
        value = match.group(1).strip()
        if value:
            asset = query.filter(func.lower(SoftwareAsset.custom_tag) == value.lower()).first()
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
