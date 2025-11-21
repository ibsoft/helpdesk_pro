# -*- coding: utf-8 -*-
"""
Fleet Monitoring blueprint scaffolding.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import os
import json
import math
import secrets
import tempfile
import base64
import shutil
import hashlib
from collections import Counter
from copy import deepcopy
from zoneinfo import ZoneInfo
from types import SimpleNamespace

from flask import Blueprint, render_template, abort, request, jsonify, Response, current_app, flash, redirect, url_for, session, send_file
from flask_login import login_required, current_user
from flask_babel import gettext as _
from sqlalchemy import and_, func, or_, cast

from app import db
from app.models import (
    FleetHost,
    FleetMessage,
    FleetModuleSettings,
    FleetAlert,
    FleetRemoteCommand,
    FleetFileTransfer,
    FleetApiKey,
    FleetScreenshot,
    FleetAgentDownloadLink,
    FleetScheduledJob,
)
from app.utils.files import secure_filename

ATHENS_TZ = ZoneInfo("Europe/Athens")


def _format_ts(ts):
    if not ts:
        return "—"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(ATHENS_TZ).strftime("%d/%m/%Y %H:%M")


def _hash_file(path: str) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()
from app.permissions import get_module_access, require_module_write


fleet_bp = Blueprint("fleet", __name__, url_prefix="/fleet")
fleet_agent_bp = Blueprint("fleet_agent_api", __name__)


def _require_view_permission():
    if not current_user.is_authenticated:
        abort(403)
    access = get_module_access(current_user, "fleet_monitoring")
    if access not in {"read", "write"}:
        abort(403)
    return access


def _agent_json_error(message: str, status: int = 400):
    return jsonify({"error": message}), status


def _find_active_api_key(token: str | None):
    if not token:
        return None
    candidates = FleetApiKey.query.filter_by(active=True).all()
    for candidate in candidates:
        if candidate.matches(token):
            return candidate
    return None


def _remote_actions_context(host: FleetHost):
    remote_commands = (
        FleetRemoteCommand.query.filter_by(host_id=host.id)
        .order_by(FleetRemoteCommand.created_at.desc())
        .limit(10)
        .all()
    )
    file_transfers = (
        FleetFileTransfer.query.filter_by(host_id=host.id)
        .order_by(FleetFileTransfer.created_at.desc())
        .limit(10)
        .all()
    )
    pending_commands = any(
        (cmd.status or "").lower() in {"pending", "assigned"}
        for cmd in remote_commands
    )
    pending_transfers = any(not transfer.consumed_at for transfer in file_transfers)
    return remote_commands, file_transfers, (pending_commands or pending_transfers)


def _render_remote_actions_panel(host: FleetHost):
    remote_commands, file_transfers, pending_actions = _remote_actions_context(host)
    return render_template(
        "fleet/_remote_actions_panel.html",
        host=host,
        remote_commands=remote_commands,
        file_transfers=file_transfers,
        format_ts=_format_ts,
        pending_actions=pending_actions,
    )


def _remote_panel_response(host: FleetHost, status: int = 200):
    html = _render_remote_actions_panel(host)
    return jsonify({"html": html}), status


def _build_host_snapshot_context(host: FleetHost):
    snapshot_data = (
        host.latest_state.snapshot if host.latest_state and host.latest_state.snapshot else None
    )
    snapshot_ts = (
        host.latest_state.updated_at if host.latest_state and host.latest_state.snapshot else None
    )
    if not snapshot_data:
        latest_snapshot_msg = (
            FleetMessage.query.filter_by(host_id=host.id, category="host", subtype="snapshot")
            .order_by(FleetMessage.ts.desc())
            .first()
        )
        if latest_snapshot_msg:
            snapshot_data = latest_snapshot_msg.payload or {}
            snapshot_ts = latest_snapshot_msg.ts
    snapshot_available = snapshot_data is not None
    snapshot = _merge_snapshot_defaults(snapshot_data)
    events_block = snapshot.get("events", {}) or {}
    health_cards = {
        "cpu": snapshot.get("cpuPct"),
        "ram": snapshot.get("ram", {}),
        "disk": snapshot.get("disk", {}),
        "updates": snapshot.get("updates", {}),
        "antivirus": snapshot.get("antivirus", {}),
        "firewall": snapshot.get("firewall", {}),
        "events": events_block,
    }
    firewall_card = health_cards["firewall"] or {}
    if firewall_card.get("domain") is None and snapshot.get("firewallDomain") is not None:
        firewall_card["domain"] = snapshot.get("firewallDomain")
    if firewall_card.get("privateProfile") is None and snapshot.get("firewallPrivate") is not None:
        firewall_card["privateProfile"] = snapshot.get("firewallPrivate")
    if firewall_card.get("publicProfile") is None and snapshot.get("firewallPublic") is not None:
        firewall_card["publicProfile"] = snapshot.get("firewallPublic")
    if firewall_card.get("anyProfileEnabled") is None:
        firewall_card["anyProfileEnabled"] = (
            snapshot.get("firewallDomain")
            or snapshot.get("firewallPrivate")
            or snapshot.get("firewallPublic")
        )
    health_cards["firewall"] = firewall_card
    health_cards["firewall_enabled"] = bool(firewall_card.get("anyProfileEnabled"))
    ram_pct = None
    ram_info = health_cards.get("ram") or {}
    try:
        used = ram_info.get("usedMB")
        total = ram_info.get("totalMB")
        if used is not None and total:
            ram_pct = round((used / total) * 100, 1)
    except (TypeError, ZeroDivisionError):
        ram_pct = None
    health_cards["ram_pct"] = ram_pct
    updates_block = health_cards.get("updates") or {}
    updates_last_check = updates_block.get("lastCheck")
    if isinstance(updates_last_check, str):
        try:
            updates_last_check_dt = datetime.fromisoformat(updates_last_check.replace("Z", "+00:00"))
        except ValueError:
            updates_last_check_dt = None
    elif isinstance(updates_last_check, datetime):
        updates_last_check_dt = updates_last_check
    else:
        updates_last_check_dt = None
    health_cards["updates_last_check_dt"] = updates_last_check_dt

    screenshot_data = (
        host.latest_state.screenshot.data_base64 if host.latest_state and host.latest_state.screenshot else None
    )
    if not screenshot_data and host.id:
        latest_screenshot = (
            FleetScreenshot.query.filter_by(host_id=host.id)
            .order_by(FleetScreenshot.created_at.desc())
            .first()
        )
        if latest_screenshot:
            screenshot_data = latest_screenshot.data_base64
    active_alerts = (
        FleetAlert.query.filter_by(host_id=host.id, resolved_at=None)
        .order_by(FleetAlert.triggered_at.desc())
        .all()
    )
    event_errors = events_block.get("errors") or []
    event_errors_count = events_block.get("errors24h") or 0
    if event_errors_count and not any(alert.rule_key == "events" for alert in active_alerts):
        active_alerts.append(
            SimpleNamespace(
                rule_key="events",
                severity="warning",
                message=_("%(count)s error events reported in the last 24h.", count=event_errors_count),
                triggered_at=snapshot_ts or datetime.utcnow(),
            )
        )

    primary_ip = snapshot.get("network", {}).get("primaryIP")
    return {
        "snapshot_available": snapshot_available,
        "snapshot_timestamp": snapshot_ts,
        "health_cards": health_cards,
        "screenshot_data": screenshot_data,
        "active_alerts": active_alerts,
        "event_errors": event_errors,
        "event_errors_count": event_errors_count,
        "primary_ip": primary_ip,
    }


def _is_ajax_request() -> bool:
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _parse_agent_isoformat(value):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _command_requested_by(command: FleetRemoteCommand) -> str | None:
    issuer = getattr(command, "issued_by", None)
    if not issuer:
        return None
    return issuer.email or issuer.full_name or issuer.username


def _build_agent_command_payloads(command: FleetRemoteCommand):
    script_text = command.command or ""
    script_b64 = base64.b64encode(script_text.encode("utf-8")).decode("ascii")
    requested_by = _command_requested_by(command)
    args = {"requestedBy": requested_by} if requested_by else {}
    task_payload = {
        "id": command.id,
        "name": "run_ps_script",
        "script": script_text,
        "script_b64": script_b64,
    }
    legacy_payload = {
        "id": command.id,
        "command": script_text,
        "language": "powershell",
        "script_b64": script_b64,
    }
    if args:
        task_payload["args"] = args
        legacy_payload["args"] = args
    return task_payload, legacy_payload


def _parse_datetime_local(value: str | None):
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    normalized = text.replace("T", " ")
    try:
        dt = datetime.strptime(normalized, "%Y-%m-%d %H:%M")
        return dt.replace(tzinfo=ATHENS_TZ).astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ATHENS_TZ)
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        return None


def _dispatch_due_jobs(host_scope: FleetHost | None = None, action_filter: set[str] | None = None):
    now = datetime.utcnow()
    due_jobs = (
        FleetScheduledJob.query.filter(
            FleetScheduledJob.status == "scheduled",
            FleetScheduledJob.run_at <= now,
        )
        .order_by(FleetScheduledJob.run_at.asc())
        .all()
    )
    if not due_jobs:
        return
    host_cache: dict[int, FleetHost] = {}
    upload_root = current_app.config.get("FLEET_UPLOAD_FOLDER") or os.path.join(
        current_app.instance_path, "fleet_uploads"
    )
    os.makedirs(upload_root, exist_ok=True)
    for job in due_jobs:
        if action_filter and job.action_type not in action_filter:
            continue
        target_ids_raw = job.target_hosts or []
        target_ids = []
        for raw in target_ids_raw:
            try:
                target_ids.append(int(raw))
            except (TypeError, ValueError):
                continue
        all_targets = target_ids[:]
        payload = job.payload or {}
        pending_hosts = payload.get("pending_hosts") if isinstance(payload, dict) else None
        if pending_hosts:
            normalized = []
            for ph in pending_hosts:
                try:
                    ph_int = int(ph)
                except (TypeError, ValueError):
                    continue
                if ph_int in all_targets:
                    normalized.append(ph_int)
            pending_hosts = normalized
        if not pending_hosts:
            pending_hosts = target_ids[:]
        scoped_target_ids = target_ids[:]
        if host_scope:
            if host_scope.id not in pending_hosts:
                continue
            scoped_target_ids = [host_scope.id]
        payload = job.payload or {}
        script_text = payload.get("script") if job.action_type == "command" else None
        upload_meta = payload.get("upload") if job.action_type == "upload" else None
        processed_hosts = set()
        for host_id in scoped_target_ids:
            if host_id not in pending_hosts:
                continue
            if host_scope and host_id != host_scope.id:
                continue
            host = host_cache.get(host_id)
            if not host:
                host = FleetHost.query.get(host_id)
                if not host:
                    continue
                host_cache[host_id] = host
            if job.action_type == "command" and script_text:
                existing_cmd = (
                    FleetRemoteCommand.query.filter_by(host_id=host.id, source_job_id=job.id)
                    .filter(FleetRemoteCommand.status.in_(["pending", "assigned"]))
                    .first()
                )
                if existing_cmd:
                    processed_hosts.add(host_id)
                    continue
                remote_command = FleetRemoteCommand(
                    host_id=host.id,
                    issued_by_user_id=job.created_by_user_id,
                    command=script_text,
                    status="pending",
                    source_job_id=job.id,
                )
                db.session.add(remote_command)
            elif job.action_type == "upload" and upload_meta:
                src_path = upload_meta.get("stored_path")
                filename = upload_meta.get("filename") or os.path.basename(src_path or "")
                if not src_path or not os.path.exists(src_path):
                    continue
                host_folder = os.path.join(upload_root, str(host.id))
                os.makedirs(host_folder, exist_ok=True)
                token = secrets.token_hex(6)
                dest_name = f"{job.id}_{token}_{filename}"
                dest_path = os.path.join(host_folder, dest_name)
                try:
                    shutil.copy2(src_path, dest_path)
                except OSError:
                    continue
                checksum_value = None
                try:
                    checksum_value = _hash_file(dest_path)
                except OSError:
                    checksum_value = None
                transfer = FleetFileTransfer(
                    host_id=host.id,
                    uploaded_by_user_id=job.created_by_user_id,
                    filename=filename,
                    stored_path=dest_path,
                    mime_type=None,
                    size_bytes=os.path.getsize(dest_path),
                    checksum=checksum_value,
                    source_job_id=job.id,
                )
                db.session.add(transfer)
            processed_hosts.add(host_id)
        pending_hosts = [h for h in pending_hosts if h not in processed_hosts]
        job_payload = (job.payload or {}).copy()
        job_payload["pending_hosts"] = pending_hosts[:]
        job.payload = job_payload
        if not pending_hosts:
            if job.recurrence == "once":
                job.status = "completed"
            elif job.recurrence == "daily":
                job.run_at = (job.run_at or now) + timedelta(days=1)
                job.payload["pending_hosts"] = all_targets[:]
            elif job.recurrence == "weekly":
                job.run_at = (job.run_at or now) + timedelta(days=7)
                job.payload["pending_hosts"] = all_targets[:]
        if job.recurrence in {"daily", "weekly"} and not pending_hosts:
            job.status = "scheduled"
        job.updated_at = now
    db.session.commit()


def _authenticate_agent_request(expected_agent_id: str | None = None):
    token = (
        request.headers.get("X-API-Key")
        or request.args.get("api_key")
        or (request.get_json(silent=True) or {}).get("apiKey")
    )
    if not token:
        return None, _agent_json_error("Missing API key.", 401)
    data_agent_id = (
        request.headers.get("X-Agent-ID")
        or request.args.get("agent")
        or (request.get_json(silent=True) or {}).get("agentId")
    )
    agent_id = data_agent_id or expected_agent_id
    if not agent_id:
        return None, _agent_json_error("Missing agent identifier.", 401)
    if expected_agent_id and agent_id.lower() != expected_agent_id.lower():
        return None, _agent_json_error("Agent identifier mismatch.", 403)
    api_key_entry = _find_active_api_key(token)
    if not api_key_entry:
        return None, _agent_json_error("Invalid or expired API key.", 401)
    host = FleetHost.query.filter_by(agent_id=agent_id).first()
    if not host:
        return None, _agent_json_error("Unknown agent.", 404)
    return host, None


def _gather_dashboard_metrics(hosts):
    settings = FleetModuleSettings.get()
    host_payloads = []
    os_counts = {"windows": 0, "linux": 0, "macos": 0, "other": 0}
    now_utc = datetime.utcnow()
    online_window = current_app.config.get("FLEET_ONLINE_WINDOW_MINUTES", 10)
    online_cutoff = now_utc - timedelta(minutes=online_window)
    online_hosts = 0
    cpu_samples = []
    health_counts = {"good": 0, "warning": 0, "critical": 0}

    host_ids = [host.id for host in hosts if host.id]
    latest_snapshots: dict[int, dict] = {}
    if host_ids:
        snapshot_rows = (
            FleetMessage.query.filter(
                FleetMessage.host_id.in_(host_ids),
                FleetMessage.category == "host",
                FleetMessage.subtype == "snapshot",
            )
            .order_by(FleetMessage.host_id.asc(), FleetMessage.ts.desc())
            .all()
        )
        for row in snapshot_rows:
            if row.host_id not in latest_snapshots:
                latest_snapshots[row.host_id] = row.payload or {}

    for host in hosts:
        snapshot_data = latest_snapshots.get(host.id)
        if not snapshot_data:
            snapshot_data = host.latest_state.snapshot if host.latest_state and host.latest_state.snapshot else None
        snapshot = _merge_snapshot_defaults(snapshot_data)

        cpu_pct = snapshot.get("cpuPct")
        ram_used = snapshot.get("ram", {}).get("usedMB")
        ram_total = snapshot.get("ram", {}).get("totalMB")
        ram_pct = None
        if ram_used and ram_total:
            try:
                ram_pct = round((ram_used / ram_total) * 100, 1)
            except ZeroDivisionError:
                ram_pct = None
        disk_pct = snapshot.get("disk", {}).get("maxUsedPct")
        errors = snapshot.get("events", {}).get("errors24h")
        os_family = (host.os_family or "").lower()
        if "win" in os_family:
            os_counts["windows"] += 1
        elif "mac" in os_family or "darwin" in os_family:
            os_counts["macos"] += 1
        elif "linux" in os_family:
            os_counts["linux"] += 1
        else:
            os_counts["other"] += 1
        host_online = bool(host.last_seen_at and host.last_seen_at >= online_cutoff)
        if host_online:
            online_hosts += 1
        if cpu_pct is not None:
            cpu_samples.append(cpu_pct)
        disk_pct = snapshot.get("disk", {}).get("maxUsedPct")
        errors = snapshot.get("events", {}).get("errors24h")
        pending_updates = snapshot.get("updates", {}).get("pending")
        health = "good"
        if (cpu_pct or 0) >= 90 or (disk_pct or 0) >= 90 or (errors or 0) >= 10 or (pending_updates or 0) >= 5:
            health = "critical"
        elif (cpu_pct or 0) >= 70 or (disk_pct or 0) >= 80 or (errors or 0) > 0 or (pending_updates or 0) > 0:
            health = "warning"
        health_counts[health] += 1
        host_payloads.append(
            {
                "id": host.id,
                "name": host.display_name or host.agent_id,
                "agent": host.agent_id,
                "os": host.os_family or _("Unknown"),
                "location": host.location or _("No location set"),
                "lat": host.latitude,
                "lng": host.longitude,
                "cpu": cpu_pct,
                "ram": ram_pct,
                "disk": disk_pct,
                "errors": errors or 0,
                "updated": host.last_seen_at.isoformat() if host.last_seen_at else None,
                "status": "online" if host_online else "offline",
                "health": health,
                "pending_updates": pending_updates or 0,
                "primary_ip": snapshot.get("network", {}).get("primaryIP"),
                "ram_used": ram_used,
                "ram_total": ram_total,
                "os_family": host.os_family or "Other",
            }
        )
    avg_cpu = round(sum(cpu_samples) / len(cpu_samples), 1) if cpu_samples else None
    last_ingest_ts = db.session.query(func.max(FleetMessage.ts)).scalar()
    active_alerts = FleetAlert.query.filter_by(resolved_at=None).count()
    stats = {
        "total_hosts": len(hosts),
        "online_hosts": online_hosts,
        "offline_hosts": max(len(hosts) - online_hosts, 0),
        "alerts": active_alerts,
        "avg_cpu": avg_cpu,
        "last_ingest": last_ingest_ts,
        "health_counts": health_counts,
    }
    return host_payloads, os_counts, stats, settings


@fleet_bp.route("/", methods=["GET"])
@login_required
def dashboard():
    module_access = _require_view_permission()
    hosts = FleetHost.query.order_by(FleetHost.display_name.asc()).all()
    host_payloads, os_counts, stats, settings = _gather_dashboard_metrics(hosts)
    map_center_lat = getattr(settings, "map_center_lat", 37.9838)
    map_center_lng = getattr(settings, "map_center_lng", 23.7275)
    stats_json = dict(stats)
    last_ingest = stats_json.get("last_ingest")
    stats_json["last_ingest"] = last_ingest.isoformat() if last_ingest else None
    os_counts_json = dict(os_counts)
    return render_template(
        "fleet/dashboard.html",
        hosts=hosts,
        settings=settings,
        map_center_lat=map_center_lat,
        map_center_lng=map_center_lng,
        module_access=module_access,
        host_payloads=host_payloads,
        os_counts=os_counts,
        stats=stats,
        stats_json=stats_json,
        os_counts_json=os_counts_json,
        format_ts=_format_ts,
    )


@fleet_bp.route("/api/dashboard-data", methods=["GET"])
@login_required
def dashboard_data():
    _require_view_permission()
    hosts = FleetHost.query.order_by(FleetHost.display_name.asc()).all()
    host_payloads, os_counts, stats, _settings = _gather_dashboard_metrics(hosts)
    stats_payload = dict(stats)
    last_ingest = stats_payload.get("last_ingest")
    stats_payload["last_ingest"] = last_ingest.isoformat() if last_ingest else None
    return jsonify(
        {
            "stats": stats_payload,
            "os_counts": os_counts,
            "hosts": host_payloads,
        }
    )


@fleet_bp.route("/hosts/<int:host_id>", methods=["GET"])
@login_required
def host_detail(host_id: int):
    module_access = _require_view_permission()
    settings = FleetModuleSettings.get()
    host = FleetHost.query.get_or_404(host_id)
    online_window = current_app.config.get("FLEET_ONLINE_WINDOW_MINUTES", 10)
    online_cutoff = datetime.utcnow() - timedelta(minutes=online_window)
    host_online = bool(host.last_seen_at and host.last_seen_at >= online_cutoff)
    base_query = FleetMessage.query.filter_by(host_id=host.id)
    query = base_query
    category_count_query = base_query
    category = request.args.get("category", "").strip()
    subtype = request.args.get("subtype", "").strip()
    level = request.args.get("level", "").strip()
    text = request.args.get("q", "").strip()
    if text.lower() == "none":
        text = ""
    if category:
        condition = FleetMessage.category.ilike(f"%{category}%")
        query = query.filter(condition)
        category_count_query = category_count_query.filter(condition)
    if subtype:
        condition = FleetMessage.subtype.ilike(f"%{subtype}%")
        query = query.filter(condition)
        category_count_query = category_count_query.filter(condition)
    if level:
        condition = FleetMessage.level.ilike(f"%{level}%")
        query = query.filter(condition)
        category_count_query = category_count_query.filter(condition)
    textless_query = query
    category_count_no_text = category_count_query
    filtered_messages_cache: list[FleetMessage] | None = None
    if text:
        text_like = f"%{text}%"
        payload_text = cast(FleetMessage.payload, db.Text)
        condition = or_(
            FleetMessage.category.ilike(text_like),
            FleetMessage.subtype.ilike(text_like),
            FleetMessage.level.ilike(text_like),
            payload_text.ilike(text_like),
        )
        filtered_ids = [
            row.id
            for row in query.filter(condition).with_entities(FleetMessage.id).order_by(FleetMessage.ts.desc()).all()
        ]
        if filtered_ids:
            filtered_messages_cache = (
                textless_query.filter(FleetMessage.id.in_(filtered_ids)).order_by(FleetMessage.ts.desc()).all()
            )
        else:
            search_limit = current_app.config.get("FLEET_TEXT_SEARCH_SCAN_LIMIT", 5000)
            search_query = textless_query.order_by(FleetMessage.ts.desc())
            if search_limit:
                search_query = search_query.limit(search_limit)
            candidates = search_query.all()
            text_lower = text.lower()
            filtered_messages_cache = []
            for row in candidates:
                payload_blob = ""
                try:
                    payload_blob = json.dumps(row.payload or {}, sort_keys=True, ensure_ascii=False)
                except (TypeError, ValueError):
                    pass
                combined_parts = [
                    (row.category or "").lower(),
                    (row.subtype or "").lower(),
                    (row.level or "").lower(),
                    payload_blob.lower(),
                ]
                combined_text = " ".join(part for part in combined_parts if part)
                if text_lower in combined_text:
                    filtered_messages_cache.append(row)
        if filtered_messages_cache is not None:
            filtered_ids = [msg.id for msg in filtered_messages_cache]
            if filtered_ids:
                query = textless_query.filter(FleetMessage.id.in_(filtered_ids))
                category_count_query = category_count_no_text.filter(FleetMessage.id.in_(filtered_ids))
            else:
                query = textless_query.filter(db.text("1=0"))
                category_count_query = category_count_no_text.filter(db.text("1=0"))

    export = request.args.get("export")
    if export == "json":
        if filtered_messages_cache is not None:
            export_rows = filtered_messages_cache
        else:
            export_rows = query.order_by(FleetMessage.ts.desc()).all()
        data = [
            {
                "ts": msg.ts.isoformat(),
                "category": msg.category,
                "subtype": msg.subtype,
                "level": msg.level,
                "payload": msg.payload,
            }
            for msg in export_rows
        ]
        return jsonify({"host": host.agent_id, "messages": data})

    per_page_param = request.args.get("per_page")
    show_all_entries = (per_page_param or "").strip().lower() == "all"
    if show_all_entries:
        per_page = None
    else:
        try:
            per_page = int(per_page_param or current_app.config.get("FLEET_HOST_FEED_PAGE_SIZE", 25))
        except (TypeError, ValueError):
            per_page = current_app.config.get("FLEET_HOST_FEED_PAGE_SIZE", 25)
        per_page = max(5, min(per_page, 200))
    page = request.args.get("page", 1, type=int) or 1
    if filtered_messages_cache is not None:
        total_matches = len(filtered_messages_cache)
        sorted_cache = sorted(filtered_messages_cache, key=lambda m: m.ts or datetime.min, reverse=True)
        if show_all_entries:
            messages = sorted_cache
            pagination = SimpleNamespace(
                page=1,
                per_page=total_matches,
                total=total_matches,
                pages=1,
                has_prev=False,
                has_next=False,
                prev_num=1,
                next_num=1,
                show_all=True,
            )
        else:
            pages = max(1, math.ceil(total_matches / per_page)) if total_matches else 1
            page = max(1, min(page, pages))
            start = (page - 1) * per_page
            end = start + per_page
            messages = sorted_cache[start:end]
            pagination = SimpleNamespace(
                page=page,
                per_page=per_page,
                total=total_matches,
                pages=pages,
                has_prev=page > 1 and total_matches > 0,
                has_next=page < pages and total_matches > 0,
                prev_num=page - 1 if page > 1 else 1,
                next_num=page + 1 if page < pages else pages,
                show_all=False,
            )
        message_payload_map = {msg.id: msg.payload for msg in messages}
        counts = Counter(msg.category or "" for msg in filtered_messages_cache)
        category_counts = [
            {"name": name or _("Uncategorized"), "raw": name or "", "count": count}
            for name, count in counts.most_common(12)
        ]
    else:
        ordered_query = query.order_by(FleetMessage.ts.desc())
        if show_all_entries:
            messages = ordered_query.all()
            total_matches = len(messages)
            pagination = SimpleNamespace(
                page=1,
                per_page=total_matches,
                total=total_matches,
                pages=1,
                has_prev=False,
                has_next=False,
                prev_num=1,
                next_num=1,
                show_all=True,
            )
        else:
            pagination = ordered_query.paginate(page=page, per_page=per_page, error_out=False)
            messages = pagination.items
            pagination.show_all = False  # type: ignore[attr-defined]
        message_payload_map = {msg.id: msg.payload for msg in messages}
        category_rows = (
            category_count_query.with_entities(
                FleetMessage.category.label("name"),
                func.count(FleetMessage.id).label("count"),
            )
            .group_by(FleetMessage.category)
            .order_by(func.count(FleetMessage.id).desc())
            .limit(12)
            .all()
        )
        category_counts = [
            {"name": row.name or _("Uncategorized"), "raw": row.name or "", "count": row.count}
            for row in category_rows
        ]
    category_icon_defs = [
        ("host", _("Host"), "fa-display"),
        ("device", _("Devices"), "fa-microchip"),
        ("network", _("Network"), "fa-diagram-project"),
        ("event", _("Events"), "fa-bug"),
        ("security", _("Security"), "fa-shield-heart"),
        ("update", _("Updates"), "fa-cloud-arrow-down"),
    ]
    counts_map = {item["raw"]: item["count"] for item in category_counts}
    icon_map = {raw: (label, icon) for raw, label, icon in category_icon_defs}
    category_pills = []
    for raw, label, icon in category_icon_defs:
        category_pills.append({
            "raw": raw,
            "label": label,
            "icon": icon,
            "count": counts_map.get(raw, 0),
        })
    for item in category_counts:
        if item["raw"] in icon_map or not item["raw"]:
            continue
        category_pills.append(
            {
                "raw": item["raw"],
                "label": item["name"],
                "icon": "fa-tag",
                "count": item["count"],
            }
        )

    snapshot_context = _build_host_snapshot_context(host)
    snapshot_available = snapshot_context["snapshot_available"]
    snapshot_ts = snapshot_context["snapshot_timestamp"]
    health_cards = snapshot_context["health_cards"]
    screenshot_data = snapshot_context["screenshot_data"]
    active_alerts = snapshot_context["active_alerts"]
    event_errors = snapshot_context["event_errors"]
    primary_ip = snapshot_context["primary_ip"]

    template_context = {
        "host": host,
        "host_online": host_online,
        "messages": messages,
        "module_access": module_access,
        "filters": {
            "category": category or "",
            "subtype": subtype or "",
            "level": level or "",
            "q": text or "",
            "per_page": per_page_param or "",
        },
        "health_cards": health_cards,
        "screenshot_data": screenshot_data,
        "active_alerts": active_alerts,
        "primary_ip": primary_ip,
        "format_ts": _format_ts,
        "message_payload_map": message_payload_map,
        "settings": settings,
        "pagination": pagination,
        "category_counts": category_counts,
        "category_pills": category_pills,
        "last_ingest_ts": host.last_seen_at,
        "snapshot_timestamp": snapshot_ts,
        "snapshot_available": snapshot_available,
        "event_errors": event_errors,
        "remote_actions_html": _render_remote_actions_panel(host),
    }

    if request.args.get("partial") == "messages":
        return render_template("fleet/_messages_panel.html", **template_context)

    return render_template("fleet/host_detail.html", **template_context)


@fleet_bp.get("/hosts/<int:host_id>/remote-panel")
@login_required
def remote_actions_panel(host_id: int):
    _require_view_permission()
    host = FleetHost.query.get_or_404(host_id)
    return _remote_panel_response(host)


@fleet_bp.post("/hosts/<int:host_id>/messages/purge")
@login_required
def purge_host_messages(host_id: int):
    require_module_write("fleet_monitoring")
    host = FleetHost.query.get_or_404(host_id)
    scope = (request.form.get("scope") or "").strip().lower()
    windows = {
        "day": timedelta(days=1),
        "week": timedelta(weeks=1),
        "month": timedelta(days=30),
        "year": timedelta(days=365),
    }
    if scope not in windows:
        message = _("Select a valid purge window.")
        if _is_ajax_request():
            return jsonify({"success": False, "message": message}), 400
        flash(message, "danger")
        return redirect(url_for("fleet.host_detail", host_id=host.id))

    cutoff = datetime.utcnow() - windows[scope]
    deleted = FleetMessage.query.filter(
        FleetMessage.host_id == host.id,
        FleetMessage.ts < cutoff,
    ).delete(synchronize_session=False)
    db.session.commit()

    message = _(
        "Purged %(count)s telemetry messages older than %(scope)s.",
        count=deleted,
        scope=scope,
    )
    if _is_ajax_request():
        return jsonify({"success": True, "message": message})

    flash(message, "success")
    return redirect(url_for("fleet.host_detail", host_id=host.id))


@fleet_bp.get("/hosts/<int:host_id>/status-panel")
@login_required
def host_status_panel(host_id: int):
    _require_view_permission()
    host = FleetHost.query.get_or_404(host_id)
    settings = FleetModuleSettings.get()
    online_window = current_app.config.get("FLEET_ONLINE_WINDOW_MINUTES", 10)
    online_cutoff = datetime.utcnow() - timedelta(minutes=online_window)
    host_online = bool(host.last_seen_at and host.last_seen_at >= online_cutoff)
    snapshot_context = _build_host_snapshot_context(host)
    badge_html = render_template("fleet/_host_status_badge.html", host_online=host_online)
    health_html = render_template(
        "fleet/_system_health_body.html",
        host=host,
        settings=settings,
        snapshot_available=snapshot_context["snapshot_available"],
        snapshot_timestamp=snapshot_context["snapshot_timestamp"],
        health_cards=snapshot_context["health_cards"],
        format_ts=_format_ts,
    )
    return jsonify({"badge": badge_html, "health": health_html})


@fleet_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    require_module_write("fleet_monitoring")
    settings_obj = FleetModuleSettings.get()
    if request.method == "POST":
        try:
            settings_obj.map_zoom = int(request.form.get("map_zoom") or settings_obj.map_zoom)
        except ValueError:
            flash(_("Invalid map zoom."), "danger")
            return redirect(url_for("fleet.settings"))
        settings_obj.map_pin_icon = (request.form.get("map_pin_icon") or settings_obj.map_pin_icon).strip()
        try:
            settings_obj.retention_days_messages = int(request.form.get("retention_days_messages") or settings_obj.retention_days_messages)
            settings_obj.retention_days_screenshots = int(request.form.get("retention_days_screenshots") or settings_obj.retention_days_screenshots)
        except ValueError:
            flash(_("Retention values must be integers."), "danger")
            return redirect(url_for("fleet.settings"))
        settings_obj.show_dashboard_screenshots = bool(request.form.get("show_dashboard_screenshots"))
        alert_rules_raw = request.form.get("alert_rules_json") or "{}"
        try:
            settings_obj.default_alert_rules = json.loads(alert_rules_raw)
        except json.JSONDecodeError as exc:
            flash(_("Alert rules must be valid JSON: %(msg)s", msg=exc), "danger")
            return redirect(url_for("fleet.settings"))
        db.session.commit()
        flash(_("Fleet settings updated."), "success")
        return redirect(url_for("fleet.settings"))
    api_keys = FleetApiKey.query.order_by(FleetApiKey.created_at.desc()).all()
    pending_api_key = session.get("fleet_pending_api_key")
    status_summary = {
        "ingest_enabled": current_app.config.get("FLEET_INGEST_ENABLED", True),
        "ingest_endpoint": f"{current_app.config.get('FLEET_INGEST_HOST', '0.0.0.0')}:{current_app.config.get('FLEET_INGEST_PORT', 8449)}",
        "host_count": FleetHost.query.count(),
        "api_keys": len(api_keys),
        "rule_count": len(settings_obj.default_alert_rules or {}),
        "last_updated": settings_obj.updated_at,
    }
    installer_path = current_app.config.get("FLEET_AGENT_INSTALLER_PATH") or os.path.join(
        current_app.instance_path, "Telemetry_Agent.msi"
    )
    installer_info = None
    if installer_path and os.path.exists(installer_path):
        try:
            stat = os.stat(installer_path)
            installer_info = {
                "path": installer_path,
                "filename": os.path.basename(installer_path) or "Telemetry_Agent.msi",
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime),
            }
        except OSError:
            installer_info = None
    download_links = (
        FleetAgentDownloadLink.query.order_by(FleetAgentDownloadLink.created_at.desc())
        .limit(25)
        .all()
    )
    link_default_ttl = current_app.config.get("FLEET_AGENT_LINK_DEFAULT_TTL_DAYS", 7)
    return render_template(
        "fleet/settings.html",
        settings=settings_obj,
        api_keys=api_keys,
        pending_api_key=pending_api_key,
        status_summary=status_summary,
        agent_installer_info=installer_info,
        agent_download_links=download_links,
        agent_link_default_ttl=link_default_ttl,
    )


@fleet_bp.route("/jobs", methods=["GET", "POST"])
@login_required
def job_scheduler():
    module_access = get_module_access(current_user, "fleet_job_scheduler")
    if module_access not in {"read", "write"}:
        abort(403)
    context = _build_job_scheduler_context()
    host_lookup = context.get("host_lookup", {})
    if request.method == "POST":
        require_module_write("fleet_job_scheduler")
        name = (request.form.get("job_name") or "").strip()
        action = (request.form.get("job_action") or "command").strip().lower()
        recurrence = (request.form.get("job_recurrence") or "once").strip().lower()
        run_at = _parse_datetime_local(request.form.get("job_run_at"))
        selected_hosts = []
        for raw_id in request.form.getlist("job_hosts"):
            raw_id = (raw_id or "").strip()
            if not raw_id:
                continue
            try:
                host_id = int(raw_id)
            except ValueError:
                continue
            if host_id in host_lookup:
                selected_hosts.append(host_id)
        payload = {}
        notes = (request.form.get("job_notes") or "").strip()
        if notes:
            payload["notes"] = notes
        errors = []
        upload_file = None
        if not name:
            errors.append(_("Job name is required."))
        if not selected_hosts:
            errors.append(_("Select at least one host to target."))
        if not run_at:
            errors.append(_("Provide a valid schedule date and time."))
        if recurrence not in {"once", "daily", "weekly"}:
            recurrence = "once"
        if action == "upload":
            upload_file = request.files.get("job_file")
            if not upload_file or not upload_file.filename:
                errors.append(_("Choose a file to upload for scheduled delivery."))
        else:
            action = "command"
            script = (request.form.get("job_command_script") or "").strip()
            if not script:
                errors.append(_("Provide a PowerShell script to execute."))
            else:
                payload["script"] = script
        if errors:
            for err in errors:
                flash(err, "danger")
        else:
            if action == "upload" and upload_file:
                upload_root = current_app.config.get("FLEET_UPLOAD_FOLDER") or os.path.join(
                    current_app.instance_path, "fleet_uploads"
                )
                os.makedirs(upload_root, exist_ok=True)
                scheduled_dir = os.path.join(upload_root, "scheduled")
                os.makedirs(scheduled_dir, exist_ok=True)
                safe_name = secure_filename(upload_file.filename, allow_unicode=True)
                token = secrets.token_hex(8)
                stored_name = f"{token}_{safe_name}"
                stored_path = os.path.join(scheduled_dir, stored_name)
                upload_file.save(stored_path)
                payload["upload"] = {
                    "filename": safe_name,
                    "stored_path": stored_path,
                    "size": os.path.getsize(stored_path),
                }
            pending_hosts = [int(h) for h in selected_hosts]
            payload["pending_hosts"] = pending_hosts
            job = FleetScheduledJob(
                name=name,
                action_type=action,
                run_at=run_at,
                recurrence=recurrence,
                target_hosts=selected_hosts,
                payload=payload,
                created_by_user_id=current_user.id,
            )
            db.session.add(job)
            db.session.commit()
            flash(_("Fleet job '%(name)s' scheduled.", name=name), "success")
            return redirect(url_for("fleet.job_scheduler"))
    return render_template(
        "fleet/job_scheduler.html",
        module_access=module_access,
        format_ts=_format_ts,
        **context,
    )


def _build_job_scheduler_context():
    hosts = FleetHost.query.order_by(
        func.lower(func.coalesce(FleetHost.display_name, "")),
        FleetHost.agent_id.asc(),
    ).all()
    host_lookup = {host.id: host for host in hosts}
    scheduled_query = FleetScheduledJob.query.filter_by(status="scheduled")
    job_counts = {
        "total": FleetScheduledJob.query.count(),
        "scheduled": scheduled_query.count(),
        "completed": FleetScheduledJob.query.filter_by(status="completed").count(),
    }
    next_job = scheduled_query.order_by(FleetScheduledJob.run_at.asc()).first()
    jobs = (
        FleetScheduledJob.query.order_by(FleetScheduledJob.run_at.asc())
        .limit(50)
        .all()
    )
    job_forms = []
    for job in jobs:
        if job.run_at:
            run_at_dt = job.run_at
            if run_at_dt.tzinfo is None:
                run_at_dt = run_at_dt.replace(tzinfo=timezone.utc)
            run_at_local = run_at_dt.astimezone(ATHENS_TZ)
            run_at_str = run_at_local.strftime("%Y-%m-%dT%H:%M")
        else:
            run_at_str = ""
        raw_pending = []
        payload = job.payload or {}
        if isinstance(payload, dict):
            raw_pending = payload.get("pending_hosts") or []
        normalized_pending = []
        for ph in raw_pending:
            try:
                normalized_pending.append(int(ph))
            except (TypeError, ValueError):
                continue
        if not normalized_pending and (job.status or "").lower() == "scheduled":
            normalized_pending = [int(h) for h in job.target_hosts or []]
        pending_count = len(normalized_pending)
        delivered_count = max(job.target_count() - pending_count, 0)
        job_forms.append(
            {
                "id": job.id,
                "name": job.name,
                "run_at": run_at_str,
                "recurrence": job.recurrence,
                "action_type": job.action_type,
                "script": (job.payload or {}).get("script") if job.action_type == "command" else "",
                "notes": (job.payload or {}).get("notes"),
                "pending": pending_count,
                "delivered": delivered_count,
                "pending_hosts": normalized_pending,
            }
        )
    return {
        "hosts": hosts,
        "host_lookup": host_lookup,
        "job_counts": job_counts,
        "next_job": next_job,
        "jobs": jobs,
        "job_forms": job_forms,
    }


@fleet_bp.get("/jobs/timeline/partial")
@login_required
def job_scheduler_timeline_partial():
    module_access = get_module_access(current_user, "fleet_job_scheduler")
    if module_access not in {"read", "write"}:
        abort(403)
    context = _build_job_scheduler_context()
    context["module_access"] = module_access
    html = render_template("fleet/_job_timeline.html", format_ts=_format_ts, **context)
    next_job = context.get("next_job")
    next_run = _format_ts(next_job.run_at) if next_job and next_job.run_at else _format_ts(None)
    return jsonify(
        {
            "html": html,
            "counts": context.get("job_counts", {}),
            "next_run": next_run,
        }
    )


@fleet_bp.post("/jobs/<int:job_id>/cancel")
@login_required
def cancel_scheduled_job(job_id: int):
    require_module_write("fleet_job_scheduler")
    job = FleetScheduledJob.query.get_or_404(job_id)
    if job.status == "canceled":
        flash(_("Job '%(name)s' is already canceled.", name=job.name), "info")
        return redirect(url_for("fleet.job_scheduler"))
    job.status = "canceled"
    job.updated_at = datetime.utcnow()
    db.session.commit()
    flash(_("Job '%(name)s' canceled.", name=job.name), "success")
    return redirect(url_for("fleet.job_scheduler"))


@fleet_bp.post("/jobs/<int:job_id>/delete")
@login_required
def delete_scheduled_job(job_id: int):
    require_module_write("fleet_job_scheduler")
    job = FleetScheduledJob.query.get_or_404(job_id)
    db.session.delete(job)
    db.session.commit()
    flash(_("Job '%(name)s' removed permanently.", name=job.name), "success")
    return redirect(url_for("fleet.job_scheduler"))


@fleet_bp.post("/jobs/<int:job_id>/edit")
@login_required
def edit_scheduled_job(job_id: int):
    require_module_write("fleet_job_scheduler")
    job = FleetScheduledJob.query.get_or_404(job_id)
    name = (request.form.get("job_name") or "").strip()
    run_at = _parse_datetime_local(request.form.get("job_run_at"))
    recurrence = (request.form.get("job_recurrence") or job.recurrence).strip().lower()
    notes = (request.form.get("job_notes") or "").strip()
    action = job.action_type
    payload = job.payload or {}
    if job.action_type == "command":
        script = (request.form.get("job_command_script") or "").strip()
        if script:
            payload["script"] = script
    if name:
        job.name = name
    if run_at:
        job.run_at = run_at
    if recurrence in {"once", "daily", "weekly"}:
        job.recurrence = recurrence
    if notes:
        payload["notes"] = notes
    job.payload = payload
    if job.run_at and job.run_at > datetime.utcnow():
        job.status = "scheduled"
    job.updated_at = datetime.utcnow()
    db.session.commit()
    flash(_("Job '%(name)s' updated.", name=job.name), "success")
    return redirect(url_for("fleet.job_scheduler"))


@fleet_bp.post("/jobs/<int:job_id>/reschedule")
@login_required
def reschedule_scheduled_job(job_id: int):
    require_module_write("fleet_job_scheduler")
    job = FleetScheduledJob.query.get_or_404(job_id)
    new_run = _parse_datetime_local(request.form.get("job_run_at"))
    if not new_run:
        flash(_("Provide a valid date and time to reschedule the job."), "danger")
        return redirect(url_for("fleet.job_scheduler"))
    job.run_at = new_run
    job.status = "scheduled"
    payload = job.payload or {}
    normalized_targets = []
    for target in job.target_hosts or []:
        try:
            normalized_targets.append(int(target))
        except (TypeError, ValueError):
            continue
    payload["pending_hosts"] = normalized_targets
    job.payload = payload
    job.updated_at = datetime.utcnow()
    db.session.commit()
    flash(_("Job '%(name)s' rescheduled.", name=job.name), "success")
    return redirect(url_for("fleet.job_scheduler"))


@fleet_bp.route("/hosts/<int:host_id>/commands", methods=["POST"])
@login_required
def create_remote_command(host_id: int):
    require_module_write("fleet_monitoring")
    host = FleetHost.query.get_or_404(host_id)
    command = (request.form.get("command") or "").strip()
    if not command:
        if _is_ajax_request():
            return jsonify({"error": _("Command cannot be empty.")}), 400
        flash(_("Command cannot be empty."), "danger")
        return redirect(url_for("fleet.host_detail", host_id=host.id))
    entry = FleetRemoteCommand(
        host_id=host.id,
        issued_by_user_id=current_user.id,
        command=command,
        status="pending",
    )
    db.session.add(entry)
    db.session.commit()
    if _is_ajax_request():
        return _remote_panel_response(host)
    flash(_("Command queued successfully."), "success")
    return redirect(url_for("fleet.host_detail", host_id=host.id))


@fleet_bp.route("/hosts/<int:host_id>/commands/<int:command_id>/cancel", methods=["POST"])
@login_required
def cancel_remote_command(host_id: int, command_id: int):
    require_module_write("fleet_monitoring")
    host = FleetHost.query.get_or_404(host_id)
    command = (
        FleetRemoteCommand.query.filter_by(id=command_id, host_id=host.id)
        .first_or_404()
    )
    if command.status not in {"pending", "assigned"}:
        if _is_ajax_request():
            return jsonify({"error": _("Command cannot be canceled once it is %(state)s.", state=command.status)}), 400
        flash(_("Command cannot be canceled once it is %(state)s.", state=command.status), "warning")
        return redirect(url_for("fleet.host_detail", host_id=host.id))
    command.status = "canceled"
    command.response = _("Command canceled by %(user)s", user=current_user.username or current_user.email)
    db.session.commit()
    if _is_ajax_request():
        return _remote_panel_response(host)
    flash(_("Command canceled."), "success")
    return redirect(url_for("fleet.host_detail", host_id=host.id))


@fleet_bp.route("/hosts/<int:host_id>/commands/clear", methods=["POST"])
@login_required
def clear_remote_commands(host_id: int):
    require_module_write("fleet_monitoring")
    host = FleetHost.query.get_or_404(host_id)
    FleetRemoteCommand.query.filter_by(host_id=host.id).delete(synchronize_session=False)
    transfers = FleetFileTransfer.query.filter_by(host_id=host.id).all()
    for transfer in transfers:
        if transfer.stored_path and os.path.exists(transfer.stored_path):
            try:
                os.remove(transfer.stored_path)
            except OSError:
                current_app.logger.warning("Failed to remove transfer file %s", transfer.stored_path)
        db.session.delete(transfer)
    db.session.commit()
    if _is_ajax_request():
        return _remote_panel_response(host)
    flash(_("Remote commands and staged uploads cleared."), "success")
    return redirect(url_for("fleet.host_detail", host_id=host.id))


@fleet_bp.route("/hosts/<int:host_id>/rdp", methods=["GET"])
@login_required
def download_rdp_file(host_id: int):
    module_access = _require_view_permission()
    if module_access not in {"read", "write"}:
        abort(403)
    host = FleetHost.query.get_or_404(host_id)
    snapshot = host.latest_state.snapshot if host.latest_state else {}
    primary_ip = snapshot.get("network", {}).get("primaryIP") if snapshot else None
    if not primary_ip:
        flash(_("No primary IP reported for this host yet."), "warning")
        return redirect(url_for("fleet.host_detail", host_id=host.id))
    filename = f"{(host.display_name or host.agent_id).replace(' ', '_')}.rdp"
    rdp_payload = [
        "screen mode id:i:2",
        "use multimon:i:0",
        "desktopwidth:i:1280",
        "desktopheight:i:720",
        "session bpp:i:32",
        f"full address:s:{primary_ip}",
        "prompt for credentials:i:1",
        "authentication level:i:2",
        "enablecredsspsupport:i:1",
        "audiomode:i:0",
        "redirectprinters:i:0",
        "redirectclipboard:i:1",
    ]
    response = Response("\n".join(rdp_payload), mimetype="application/x-rdp")
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response


@fleet_bp.route("/hosts/<int:host_id>/uploads", methods=["POST"])
@login_required
def upload_remote_file(host_id: int):
    require_module_write("fleet_monitoring")
    host = FleetHost.query.get_or_404(host_id)
    file = request.files.get("file")
    if not file or not file.filename:
        if _is_ajax_request():
            return jsonify({"error": _("Select a file to upload.")}), 400
        flash(_("Select a file to upload."), "danger")
        return redirect(url_for("fleet.host_detail", host_id=host.id))
    filename = secure_filename(file.filename, allow_unicode=True)
    upload_root = current_app.config.get("FLEET_UPLOAD_FOLDER") or os.path.join(
        current_app.instance_path, "fleet_uploads"
    )
    os.makedirs(upload_root, exist_ok=True)
    host_folder = os.path.join(upload_root, str(host.id))
    os.makedirs(host_folder, exist_ok=True)
    stored_path = os.path.join(host_folder, filename)
    file.save(stored_path)
    transfer = FleetFileTransfer(
        host_id=host.id,
        uploaded_by_user_id=current_user.id,
        filename=filename,
        stored_path=stored_path,
        mime_type=file.mimetype,
        size_bytes=os.path.getsize(stored_path),
    )
    db.session.add(transfer)
    db.session.commit()
    if _is_ajax_request():
        return _remote_panel_response(host)
    flash(_("File uploaded for agent pickup."), "success")
    return redirect(url_for("fleet.host_detail", host_id=host.id))


@fleet_bp.route("/hosts/<int:host_id>/uploads/<int:transfer_id>/cancel", methods=["POST"])
@login_required
def cancel_file_transfer(host_id: int, transfer_id: int):
    require_module_write("fleet_monitoring")
    host = FleetHost.query.get_or_404(host_id)
    transfer = (
        FleetFileTransfer.query.filter_by(id=transfer_id, host_id=host.id)
        .first_or_404()
    )
    if transfer.consumed_at:
        if _is_ajax_request():
            return jsonify({"error": _("Transfer already picked up by the agent.")}), 400
        flash(_("Transfer already picked up by the agent."), "warning")
        return redirect(url_for("fleet.host_detail", host_id=host.id))
    if transfer.stored_path and os.path.exists(transfer.stored_path):
        try:
            os.remove(transfer.stored_path)
        except OSError:
            current_app.logger.warning("Failed to remove transfer file %s", transfer.stored_path)
    db.session.delete(transfer)
    db.session.commit()
    if _is_ajax_request():
        return _remote_panel_response(host)
    flash(_("Pending transfer canceled."), "success")
    return redirect(url_for("fleet.host_detail", host_id=host.id))


@fleet_bp.route("/hosts/<int:host_id>/uploads/clear", methods=["POST"])
@login_required
def clear_file_transfers(host_id: int):
    require_module_write("fleet_monitoring")
    host = FleetHost.query.get_or_404(host_id)
    transfers = FleetFileTransfer.query.filter_by(host_id=host.id).all()
    for transfer in transfers:
        if transfer.stored_path and os.path.exists(transfer.stored_path):
            try:
                os.remove(transfer.stored_path)
            except OSError:
                current_app.logger.warning("Failed to remove transfer file %s", transfer.stored_path)
        db.session.delete(transfer)
    db.session.commit()
    if _is_ajax_request():
        return _remote_panel_response(host)
    flash(_("All uploaded files removed."), "success")
    return redirect(url_for("fleet.host_detail", host_id=host.id))


@fleet_bp.route("/hosts/<int:host_id>/update", methods=["POST"])
@login_required
def update_host(host_id: int):
    require_module_write("fleet_monitoring")
    host = FleetHost.query.get_or_404(host_id)

    host.display_name = (request.form.get("display_name") or host.agent_id).strip()
    host.location = (request.form.get("location") or "").strip() or None
    host.contact = (request.form.get("contact") or "").strip() or None
    host.tags = (request.form.get("tags") or "").strip() or None
    host.notes = (request.form.get("notes") or "").strip() or None
    host.map_pin_icon = (request.form.get("host_pin_icon") or host.map_pin_icon or "").strip() or None
    host.os_family = (request.form.get("os_family") or "").strip() or None
    host.os_version = (request.form.get("os_version") or "").strip() or None

    lat_raw = (request.form.get("latitude") or "").strip()
    lon_raw = (request.form.get("longitude") or "").strip()
    try:
        host.latitude = float(lat_raw) if lat_raw else None
    except ValueError:
        flash(_("Invalid latitude."), "danger")
        return redirect(url_for("fleet.host_detail", host_id=host.id))
    try:
        host.longitude = float(lon_raw) if lon_raw else None
    except ValueError:
        flash(_("Invalid longitude."), "danger")
        return redirect(url_for("fleet.host_detail", host_id=host.id))

    db.session.commit()
    flash(_("Host details updated."), "success")
    return redirect(url_for("fleet.host_detail", host_id=host.id))


@fleet_bp.route("/settings/api-keys", methods=["POST"])
@login_required
def create_fleet_api_key():
    require_module_write("fleet_monitoring")
    name = (request.form.get("name") or "").strip()
    if not name:
        flash(_("Key name is required."), "danger")
        return redirect(url_for("fleet.settings"))
    raw_value = FleetApiKey.generate_key()
    entry = FleetApiKey(name=name)
    entry.set_key(raw_value)
    expires_raw = request.form.get("expires_at")
    if expires_raw:
        try:
            entry.expires_at = datetime.fromisoformat(expires_raw)
        except ValueError:
            flash(_("Invalid expiry timestamp."), "danger")
            return redirect(url_for("fleet.settings"))
    db.session.add(entry)
    db.session.commit()
    session["fleet_pending_api_key"] = raw_value
    flash(_("API key created. Copy it from the banner above."), "success")
    return redirect(url_for("fleet.settings"))


@fleet_bp.route("/settings/api-keys/<int:key_id>/toggle", methods=["POST"])
@login_required
def toggle_fleet_api_key(key_id: int):
    require_module_write("fleet_monitoring")
    key = FleetApiKey.query.get_or_404(key_id)
    key.active = not key.active
    db.session.commit()
    flash(_("API key status updated."), "success")
    return redirect(url_for("fleet.settings"))


@fleet_bp.route("/settings/api-keys/<int:key_id>/delete", methods=["POST"])
@login_required
def delete_fleet_api_key(key_id: int):
    require_module_write("fleet_monitoring")
    key = FleetApiKey.query.get_or_404(key_id)
    db.session.delete(key)
    db.session.commit()
    flash(_("API key deleted."), "success")
    return redirect(url_for("fleet.settings"))


@fleet_bp.route("/settings/api-keys/ack", methods=["POST"])
@login_required
def acknowledge_fleet_api_key():
    require_module_write("fleet_monitoring")
    session.pop("fleet_pending_api_key", None)
    return ("", 204)


@fleet_bp.route("/settings/cleanup-offline", methods=["POST"])
@login_required
def cleanup_offline_hosts():
    require_module_write("fleet_monitoring")
    online_window = current_app.config.get("FLEET_ONLINE_WINDOW_MINUTES", 10)
    cutoff = datetime.utcnow() - timedelta(minutes=online_window)
    offline_hosts = FleetHost.query.filter(
        or_(FleetHost.last_seen_at == None, FleetHost.last_seen_at < cutoff)
    ).all()
    if not offline_hosts:
        flash(_("No offline hosts were eligible for cleanup."), "info")
        return redirect(url_for("fleet.settings"))
    removed = 0
    for host in offline_hosts:
        db.session.delete(host)
        removed += 1
    db.session.commit()
    flash(_("Removed %(count)s offline hosts and their telemetry.", count=removed), "success")
    return redirect(url_for("fleet.settings"))


@fleet_agent_bp.post("/terminal/tasks/next")
def agent_tasks_next():
    host, error = _authenticate_agent_request()
    if error:
        return error
    _dispatch_due_jobs(host_scope=host, action_filter={"command"})
    cmd = (
        FleetRemoteCommand.query.filter_by(host_id=host.id)
        .filter(FleetRemoteCommand.status.in_(["pending", "dispatched"]))
        .order_by(FleetRemoteCommand.created_at.asc())
        .first()
    )
    if not cmd:
        return ("", 204)
    cmd.status = "assigned"
    cmd.delivered_at = datetime.utcnow()
    db.session.commit()
    task_payload, legacy_payload = _build_agent_command_payloads(cmd)
    response_payload = {
        "tasks": [task_payload],
        "commands": [legacy_payload],
        "task": task_payload,
        "command": legacy_payload,
    }
    return jsonify(response_payload)


@fleet_agent_bp.post("/terminal/tasks/result")
def agent_task_result():
    data = request.get_json(silent=True)
    if data is None:
        data = request.form.to_dict() if request.form else {}
    task_id = (
        data.get("id")
        or data.get("taskId")
        or data.get("commandId")
        or data.get("command_id")
    )
    if not task_id:
        return _agent_json_error("Missing task id.", 400)
    try:
        task_id = int(task_id)
    except (TypeError, ValueError):
        return _agent_json_error("Task id must be an integer.", 400)
    host, error = _authenticate_agent_request()
    if error:
        return error
    cmd = FleetRemoteCommand.query.get_or_404(task_id)
    if cmd.host_id != host.id:
        return _agent_json_error("Task does not belong to this agent.", 403)
    status_raw = data.get("status") or data.get("Status") or "completed"
    status = status_raw.lower() if isinstance(status_raw, str) else "completed"
    exit_code = data.get("exitCode")
    stdout = data.get("stdout") or data.get("output")
    stderr = data.get("stderr") or data.get("error")
    started_at = data.get("startedAt") or data.get("started_at")
    finished_at = data.get("finishedAt") or data.get("finished_at")
    started_dt = _parse_agent_isoformat(started_at)
    finished_dt = _parse_agent_isoformat(finished_at)
    response_parts = []
    if exit_code is not None:
        response_parts.append(f"exit_code={exit_code}")
    if started_at:
        response_parts.append(f"started_at={started_at}")
    if finished_at:
        response_parts.append(f"finished_at={finished_at}")
    if stdout:
        response_parts.append(f"stdout:\n{stdout}")
    if stderr:
        response_parts.append(f"stderr:\n{stderr}")
    cmd.status = status
    cmd.response = "\n\n".join(response_parts) or data.get("response") or cmd.response
    if started_dt:
        cmd.delivered_at = started_dt
    if finished_dt:
        cmd.executed_at = finished_dt
    else:
        cmd.executed_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"success": True})


@fleet_agent_bp.get("/fleet/hosts/<string:agent_id>/uploads")
def agent_list_uploads(agent_id: str):
    host, error = _authenticate_agent_request(expected_agent_id=agent_id)
    if error:
        return error
    _dispatch_due_jobs(host_scope=host, action_filter={"upload"})
    pending = (
        FleetFileTransfer.query.filter_by(host_id=host.id, consumed_at=None)
        .order_by(FleetFileTransfer.created_at.asc())
        .all()
    )
    payload = []
    for transfer in pending:
        entry = {
            "id": transfer.id,
            "filename": transfer.filename,
            "size": transfer.size_bytes,
            "checksum": transfer.checksum or "",
        }
        if transfer.stored_path and os.path.exists(transfer.stored_path):
            entry["checksum"] = f"sha256:{_hash_file(transfer.stored_path)}"
        payload.append(entry)
    if request.args.get("format") == "jsonv2":
        return jsonify({"uploads": payload})
    return jsonify(payload)


@fleet_agent_bp.get("/fleet/hosts/<string:agent_id>/uploads/<int:file_id>")
def agent_download_upload(agent_id: str, file_id: int):
    host, error = _authenticate_agent_request(expected_agent_id=agent_id)
    if error:
        return error
    _dispatch_due_jobs(host_scope=host, action_filter={"upload"})
    transfer = FleetFileTransfer.query.get_or_404(file_id)
    if transfer.host_id != host.id:
        return _agent_json_error("File does not belong to this agent.", 403)
    if not os.path.exists(transfer.stored_path):
        return _agent_json_error("File no longer available.", 404)
    transfer.consumed_at = datetime.utcnow()
    db.session.commit()
    return send_file(
        transfer.stored_path,
        as_attachment=True,
        mimetype=transfer.mime_type or "application/octet-stream",
        download_name=transfer.filename,
    )


@fleet_bp.route("/settings/agent-installer", methods=["POST"])
@login_required
def upload_agent_installer():
    require_module_write("fleet_monitoring")
    file = request.files.get("agent_installer")
    if not file or not file.filename:
        flash(_("Select a Telemetry_Agent.msi file to upload."), "danger")
        return redirect(url_for("fleet.settings"))
    filename = secure_filename(file.filename, allow_unicode=True)
    ext = os.path.splitext(filename or "")[1].lower()
    if ext != ".msi":
        flash(_("Installer must be a .msi file."), "danger")
        return redirect(url_for("fleet.settings"))
    installer_path = current_app.config.get("FLEET_AGENT_INSTALLER_PATH") or os.path.join(
        current_app.instance_path, "Telemetry_Agent.msi"
    )
    if not installer_path:
        flash(_("Installer path is not configured."), "danger")
        return redirect(url_for("fleet.settings"))
    os.makedirs(os.path.dirname(installer_path), exist_ok=True)
    max_bytes = current_app.config.get("FLEET_AGENT_INSTALLER_MAX_BYTES", 100 * 1024 * 1024)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".msi") as tmp:
        tmp_path = tmp.name
        file.save(tmp_path)
    try:
        size_bytes = os.path.getsize(tmp_path)
        if size_bytes > max_bytes:
            flash(_("Installer exceeds maximum allowed size (%(size)s MB).", size=max_bytes // (1024 * 1024)), "danger")
            os.remove(tmp_path)
            return redirect(url_for("fleet.settings"))
        with open(tmp_path, "rb") as fh:
            magic = fh.read(4)
            if not (magic.startswith(b"MZ") or magic == b"\xd0\xcf\x11\xe0"):
                flash(_("Installer file is not a valid Windows executable."), "danger")
                os.remove(tmp_path)
                return redirect(url_for("fleet.settings"))
        shutil.move(tmp_path, installer_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    flash(_("Agent installer updated successfully."), "success")
    return redirect(url_for("fleet.settings"))


@fleet_bp.route("/settings/agent-links", methods=["POST"])
@login_required
def create_agent_download_link():
    require_module_write("fleet_monitoring")
    installer_path = current_app.config.get("FLEET_AGENT_INSTALLER_PATH") or os.path.join(
        current_app.instance_path, "Telemetry_Agent.msi"
    )
    if not installer_path or not os.path.exists(installer_path):
        flash(_("Upload the Telemetry_Agent.msi before generating links."), "danger")
        return redirect(url_for("fleet.settings"))
    default_ttl = current_app.config.get("FLEET_AGENT_LINK_DEFAULT_TTL_DAYS", 7)
    expires_days_raw = (request.form.get("expires_in_days") or "").strip()
    try:
        expires_days = int(expires_days_raw) if expires_days_raw else int(default_ttl)
    except ValueError:
        flash(_("Expiration must be a number of days."), "danger")
        return redirect(url_for("fleet.settings"))
    if expires_days <= 0:
        flash(_("Expiration must be at least one day."), "danger")
        return redirect(url_for("fleet.settings"))
    expires_at = datetime.utcnow() + timedelta(days=expires_days)
    token = secrets.token_urlsafe(32)
    link = FleetAgentDownloadLink(
        token=token,
        created_by_user_id=current_user.id,
        expires_at=expires_at,
    )
    db.session.add(link)
    db.session.commit()
    flash(_("Installer link generated."), "success")
    return redirect(url_for("fleet.settings"))


@fleet_bp.route("/settings/agent-links/<int:link_id>/revoke", methods=["POST"])
@login_required
def revoke_agent_download_link(link_id: int):
    require_module_write("fleet_monitoring")
    link = FleetAgentDownloadLink.query.get_or_404(link_id)
    if link.revoked_at:
        flash(_("Link already revoked."), "info")
        return redirect(url_for("fleet.settings"))
    link.revoked_at = datetime.utcnow()
    db.session.commit()
    flash(_("Link revoked."), "success")
    return redirect(url_for("fleet.settings"))


@fleet_bp.route("/agent/download/<token>", methods=["GET"])
def download_agent_installer(token: str):
    installer_path = current_app.config.get("FLEET_AGENT_INSTALLER_PATH")
    if not installer_path or not os.path.exists(installer_path):
        abort(404)
    link = FleetAgentDownloadLink.query.filter_by(token=token).first_or_404()
    if link.revoked_at or link.is_expired:
        abort(404)
    download_name = os.path.basename(installer_path) or "Telemetry_Agent.msi"
    return send_file(
        installer_path,
        as_attachment=True,
        download_name=download_name,
        mimetype="application/octet-stream",
    )


@fleet_bp.route("/settings/agent-installer/delete", methods=["POST"])
@login_required
def delete_agent_installer():
    require_module_write("fleet_monitoring")
    installer_path = current_app.config.get("FLEET_AGENT_INSTALLER_PATH")
    if installer_path and os.path.exists(installer_path):
        try:
            os.remove(installer_path)
            flash(_("Installer deleted."), "success")
        except OSError as exc:
            current_app.logger.warning("Failed to delete installer: %s", exc)
            flash(_("Failed to delete installer file."), "danger")
            return redirect(url_for("fleet.settings"))
    else:
        flash(_("No installer file found."), "info")
    FleetAgentDownloadLink.query.delete()
    db.session.commit()
    flash(_("All download links have been removed."), "success")
    return redirect(url_for("fleet.settings"))
HOST_SNAPSHOT_UI_DEFAULTS = {
    "cpuPct": None,
    "ram": {"usedMB": None, "totalMB": None},
    "disk": {"maxUsedPct": None, "volumes": []},
    "updates": {"pending": None, "lastCheck": None, "error": None},
    "antivirus": {"enabled": None, "upToDate": None, "products": [], "error": None},
    "firewall": {
        "domain": None,
        "privateProfile": None,
        "publicProfile": None,
        "anyProfileEnabled": None,
        "error": None,
    },
    "events": {"errors24h": None, "errors": [], "error": None},
    "network": {"adapterCount": None, "primaryIP": None},
}
def _merge_snapshot_defaults(snapshot: dict | None) -> dict:
    data = deepcopy(HOST_SNAPSHOT_UI_DEFAULTS)
    if not snapshot:
        return data
    for key, value in snapshot.items():
        if key in data and isinstance(data[key], dict) and isinstance(value, dict):
            merged = deepcopy(data[key])
            merged.update(value)
            data[key] = merged
        else:
            data[key] = value
    return data
