# -*- coding: utf-8 -*-
"""
Standalone ingestion service for Fleet Monitoring.
Runs as a lightweight Flask app on a dedicated port (default 8449) within the same process.
"""

from __future__ import annotations

import base64
import json
import os
import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from threading import Thread
from copy import deepcopy

from flask import Flask, jsonify, request, send_file
from werkzeug.serving import make_server
from sqlalchemy.exc import SQLAlchemyError

from app import db


REQUIRED_TOP_LEVEL = {"ts", "machine", "category", "subtype", "level", "payload"}
def _merge_dict(base: dict | None, incoming: dict | None) -> dict:
    result = deepcopy(base) if isinstance(base, dict) else {}
    if isinstance(incoming, dict):
        for key, value in incoming.items():
            result[key] = value
    return result


HOST_SNAPSHOT_DEFAULTS = {
    "cpuPct": None,
    "ram": {"usedMB": None, "totalMB": None},
    "disk": {"maxUsedPct": None, "volumes": []},
    "network": {"adapterCount": None, "primaryIP": None},
    "antivirus": {"enabled": None, "upToDate": None, "products": [], "error": None},
    "firewall": {
        "domain": None,
        "privateProfile": None,
        "publicProfile": None,
        "anyProfileEnabled": None,
        "error": None,
    },
    "updates": {"pending": None, "lastCheck": None, "error": None},
    "events": {"errors24h": None, "errors": [], "error": None},
    "screenshotB64": None,
}


def _iso_utc(value: str) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    tz_part = ""
    if text.endswith("Z"):
        tz_part = "+00:00"
        text = text[:-1]
    else:
        tz_match = re.search(r"([+-]\d{2}:\d{2})$", text)
        if tz_match:
            tz_part = tz_match.group(1)
            text = text[: -len(tz_part)]
    if "." in text:
        base, frac = text.split(".", 1)
        frac_digits = re.sub(r"\D", "", frac)
        if frac_digits:
            frac_digits = (frac_digits + "000000")[:6]
            text = f"{base}.{frac_digits}"
        else:
            text = base
    if tz_part:
        text = f"{text}{tz_part}"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _error(message: str, status: int = 400):
    logging.getLogger(__name__).warning("Fleet ingest error (%s): %s", status, message)
    return jsonify({"success": False, "message": message}), status


def _command_requested_by(command):
    issuer = getattr(command, "issued_by", None)
    if not issuer:
        return None
    return getattr(issuer, "email", None) or getattr(issuer, "full_name", None) or getattr(issuer, "username", None)


def _build_agent_command_payloads(command):
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


def _validate_record(record: dict) -> tuple[bool, str]:
    if not isinstance(record, dict):
        return False, "Each NDJSON line must be a JSON object."
    missing = REQUIRED_TOP_LEVEL - record.keys()
    if missing:
        return False, f"Missing required fields: {', '.join(sorted(missing))}"
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return False, "Payload must be an object."
    return True, ""


def _decode_screenshot(raw_value: str) -> bytes | None:
    if not raw_value:
        return None
    try:
        return base64.b64decode(raw_value, validate=True)
    except (ValueError, base64.binascii.Error):
        return None


def _doc_key(record: dict) -> str | None:
    key = record.get("doc_key") or record.get("docKey")
    if key:
        return str(key)
    try:
        material = json.dumps(
            [
                record.get("machine"),
                record.get("category"),
                record.get("subtype"),
                record.get("level"),
                record.get("payload"),
            ],
            sort_keys=True,
            default=str,
        )
    except (TypeError, ValueError):
        material = f"{record.get('machine')}|{record.get('category')}|{record.get('subtype')}|{record.get('level')}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _find_api_key(token: str):
    from app.models import FleetApiKey

    candidates = FleetApiKey.query.filter_by(active=True).all()
    for candidate in candidates:
        if candidate.matches(token):
            return candidate
    return None


def _purge_expired(settings):
    from app.models import FleetMessage, FleetScreenshot, FleetLatestState

    now = datetime.utcnow()
    if settings.retention_days_messages:
        cutoff = now - timedelta(days=settings.retention_days_messages)
        FleetMessage.query.filter(FleetMessage.ts < cutoff).delete(synchronize_session=False)
    if settings.retention_days_screenshots:
        cutoff = now - timedelta(days=settings.retention_days_screenshots)
        old_shots = FleetScreenshot.query.filter(FleetScreenshot.created_at < cutoff).all()
        for shot in old_shots:
            FleetLatestState.query.filter_by(screenshot_id=shot.id).update({"screenshot_id": None})
            db.session.delete(shot)
        db.session.flush()


def _ingest_ok(app_ctx) -> bool:
    return app_ctx.config.get("FLEET_INGEST_ENABLED", True)


def _evaluate_alerts(host, snapshot: dict, settings):
    from app.models import FleetAlert

    rules = settings.default_alert_rules or {}

    def _set_alert(rule_key: str, triggered: bool, message: str, severity: str = "warning"):
        existing = FleetAlert.query.filter_by(host_id=host.id, rule_key=rule_key, resolved_at=None).first()
        if triggered:
            if existing:
                existing.message = message
                existing.severity = severity
                return
            alert = FleetAlert(
                host_id=host.id,
                rule_key=rule_key,
                severity=severity,
                message=message,
                triggered_at=datetime.utcnow(),
            )
            db.session.add(alert)
        else:
            if existing:
                existing.resolved_at = datetime.utcnow()

    cpu_rule = rules.get("cpu", {})
    cpu_threshold = cpu_rule.get("threshold", 90)
    cpu_pct = snapshot.get("cpuPct")
    if cpu_pct is not None:
        _set_alert("cpu", cpu_pct >= cpu_threshold, f"CPU at {cpu_pct:.1f}% (threshold {cpu_threshold}%)", "danger")

    disk_rule = rules.get("disk", {})
    disk_threshold = disk_rule.get("threshold", 85)
    disk_pct = snapshot.get("disk", {}).get("maxUsedPct")
    if disk_pct is not None:
        _set_alert("disk", disk_pct >= disk_threshold, f"Disk usage {disk_pct:.1f}% (threshold {disk_threshold}%)", "warning")

    av_rule = rules.get("antivirus", {})
    if snapshot.get("antivirus"):
        av_enabled = snapshot["antivirus"].get("enabled")
        av_updated = snapshot["antivirus"].get("upToDate")
        _set_alert("antivirus", not (av_enabled and av_updated), "Antivirus is disabled or outdated.", "danger")

    updates_rule = rules.get("updates", {})
    update_threshold = updates_rule.get("pending", 0)
    pending_updates = snapshot.get("updates", {}).get("pending", 0)
    _set_alert("updates", pending_updates > update_threshold, f"{pending_updates} updates pending.", "warning")

    event_rule = rules.get("events", {})
    errors_threshold = event_rule.get("errors24h", 0)
    errors = snapshot.get("events", {}).get("errors24h", 0)
    _set_alert("events", errors > errors_threshold, f"{errors} errors in the last 24h.", "warning")


def _resolve_host(agent_id: str):
    from app.models import FleetHost

    return FleetHost.query.filter_by(agent_id=agent_id).first()


def create_fleet_ingest_app(main_app) -> Flask:
    ingest_app = Flask("fleet_ingest")
    ingest_app.config.update(
        {
            "SQLALCHEMY_DATABASE_URI": main_app.config["SQLALCHEMY_DATABASE_URI"],
            "SQLALCHEMY_TRACK_MODIFICATIONS": main_app.config.get("SQLALCHEMY_TRACK_MODIFICATIONS", False),
        }
    )
    db.init_app(ingest_app)

    @ingest_app.post("/ingest")
    def fleet_ingest():
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            return _error("Missing API key.", 401)
        with ingest_app.app_context():
            api_key_entry = _find_api_key(api_key)
            if not api_key_entry:
                return _error("Invalid or expired API key.", 401)

            raw_body = request.get_data(as_text=True)
            if not raw_body or not raw_body.strip():
                return _error("Empty payload.", 400)

            lines = [line.strip() for line in raw_body.splitlines() if line.strip()]
            if not lines:
                return _error("Payload contained no valid JSON lines.", 400)

            processed = 0
            errors: list[str] = []

            from app.models import (
                FleetHost,
                FleetMessage,
                FleetLatestState,
                FleetScreenshot,
                FleetModuleSettings,
            )

            settings = FleetModuleSettings.get()

            for idx, line in enumerate(lines, start=1):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    errors.append(f"Line {idx}: {exc}")
                    continue

                valid, message = _validate_record(record)
                if not valid:
                    errors.append(f"Line {idx}: {message}")
                    continue
                ts_value = _iso_utc(record["ts"])
                if not ts_value:
                    errors.append(f"Line {idx}: Invalid timestamp format.")
                    continue
                ts_utc = ts_value.replace(tzinfo=None)

                agent_id = str(record["machine"]).strip()
                if not agent_id:
                    errors.append(f"Line {idx}: Machine identifier is empty.")
                    continue

                payload = record["payload"]
                is_host_snapshot = record.get("category") == "host" and record.get("subtype") == "snapshot"
                screenshot_bytes = _decode_screenshot(payload.get("screenshotB64"))
                if is_host_snapshot:
                    payload = _normalize_host_snapshot(payload)

                try:
                    host = FleetHost.query.filter_by(agent_id=agent_id).first()
                    if not host:
                        host = FleetHost(agent_id=agent_id, display_name=agent_id)
                        db.session.add(host)

                    host.last_seen_at = ts_utc
                    host.os_family = payload.get("osFamily") or host.os_family
                    host.os_version = payload.get("osVersion") or host.os_version

                    doc_key = _doc_key(record)
                    message_entry = None
                    if doc_key:
                        message_entry = FleetMessage.query.filter_by(doc_key=doc_key).first()
                    if message_entry:
                        message_entry.host = host
                        message_entry.ts = ts_utc
                        message_entry.category = record["category"]
                        message_entry.subtype = record.get("subtype")
                        message_entry.level = record.get("level")
                        message_entry.payload = payload
                    else:
                        message_entry = FleetMessage(
                            host=host,
                            ts=ts_utc,
                            category=record["category"],
                            subtype=record.get("subtype"),
                            level=record.get("level"),
                            payload=payload,
                            doc_key=doc_key,
                        )
                        db.session.add(message_entry)

                    latest_state = host.latest_state
                    if is_host_snapshot:
                        if not latest_state:
                            latest_state = FleetLatestState(host=host, snapshot=payload, updated_at=ts_utc)
                            db.session.add(latest_state)
                        else:
                            latest_state.snapshot = payload
                            latest_state.updated_at = ts_utc

                        if screenshot_bytes:
                            if host.id is None:
                                db.session.flush()
                            screenshot_entry = latest_state.screenshot
                            if screenshot_entry:
                                screenshot_entry.data = screenshot_bytes
                            else:
                                screenshot_entry = FleetScreenshot(host=host, data=screenshot_bytes)
                                db.session.add(screenshot_entry)
                                db.session.flush()
                                latest_state.screenshot = screenshot_entry

                    db.session.flush()
                    _evaluate_alerts(host, payload, settings)
                    processed += 1
                except SQLAlchemyError as exc:
                    ingest_app.logger.exception("Failed to process fleet record.")
                    db.session.rollback()
                    errors.append(f"Line {idx}: Database error.")
                    continue

            if processed:
                try:
                    _purge_expired(settings)
                    db.session.commit()
                except SQLAlchemyError:
                    ingest_app.logger.exception("Failed to commit fleet ingestion batch.")
                    db.session.rollback()
                    return _error("Database commit failed.", 500)

            if errors:
                logging.getLogger(__name__).warning(
                    "Fleet ingest batch had %s error(s): %s",
                    len(errors),
                    "; ".join(errors[:5]),
                )
            status_code = 200 if processed and not errors else 207 if processed else 400
            return (
                jsonify({"success": processed > 0, "processed": processed, "errors": errors}),
                status_code,
            )

    @ingest_app.get("/health")
    def fleet_health():
        if not _ingest_ok(ingest_app):
            return ("Forbidden", 403)
        with ingest_app.app_context():
            from app.models import FleetMessage

            latest = (
                db.session.query(FleetMessage.ts)
                .order_by(FleetMessage.ts.desc())
                .first()
            )
            last_ts = latest[0].replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z") if latest and latest[0] else None
            return jsonify({"lastPostUtc": last_ts})

    @ingest_app.get("/commands")
    def fleet_commands():
        api_key = request.headers.get("X-API-Key")
        agent_id = (request.headers.get("X-Agent-ID") or request.args.get("agent") or "").strip()
        if not api_key or not agent_id:
            return _error("Missing API key or agent identifier.", 400)
        with ingest_app.app_context():
            api_key_entry = _find_api_key(api_key)
            if not api_key_entry:
                return _error("Invalid or expired API key.", 401)
            host = _resolve_host(agent_id)
            if not host:
                return _error("Unknown agent.", 404)
            from app.models import FleetRemoteCommand

            pending = (
                FleetRemoteCommand.query.filter_by(host_id=host.id)
                .filter(FleetRemoteCommand.status == "pending")
                .order_by(FleetRemoteCommand.created_at.asc())
                .all()
            )
            tasks_payload = []
            legacy_payload = []
            now = datetime.utcnow()
            for cmd in pending:
                cmd.status = "dispatched"
                cmd.delivered_at = now
                task_payload, legacy_payload_entry = _build_agent_command_payloads(cmd)
                tasks_payload.append(task_payload)
                legacy_payload.append(legacy_payload_entry)
            db.session.commit()
            response_payload = {
                "tasks": tasks_payload,
                "commands": legacy_payload,
                "task": tasks_payload[0] if tasks_payload else None,
                "command": legacy_payload[0] if legacy_payload else None,
            }
            return jsonify(response_payload)

    @ingest_app.post("/commands/<int:command_id>/result")
    def fleet_command_result(command_id: int):
        api_key = request.headers.get("X-API-Key")
        agent_id = (request.headers.get("X-Agent-ID") or "").strip()
        if not api_key or not agent_id:
            return _error("Missing API key or agent identifier.", 400)
        data = request.get_json() or {}
        status = (data.get("status") or "").strip().lower() or "completed"
        response_text = data.get("response")
        with ingest_app.app_context():
            api_key_entry = _find_api_key(api_key)
            if not api_key_entry:
                return _error("Invalid or expired API key.", 401)
            host = _resolve_host(agent_id)
            if not host:
                return _error("Unknown agent.", 404)
            from app.models import FleetRemoteCommand

            cmd = FleetRemoteCommand.query.get_or_404(command_id)
            if cmd.host_id != host.id:
                return _error("Command does not belong to this agent.", 403)
            cmd.status = status
            cmd.response = response_text
            cmd.executed_at = datetime.utcnow()
            db.session.commit()
            return jsonify({"success": True})

    @ingest_app.get("/files")
    def fleet_files():
        api_key = request.headers.get("X-API-Key")
        agent_id = (request.headers.get("X-Agent-ID") or request.args.get("agent") or "").strip()
        if not api_key or not agent_id:
            return _error("Missing API key or agent identifier.", 400)
        with ingest_app.app_context():
            api_key_entry = _find_api_key(api_key)
            if not api_key_entry:
                return _error("Invalid or expired API key.", 401)
            host = _resolve_host(agent_id)
            if not host:
                return _error("Unknown agent.", 404)
            from app.models import FleetFileTransfer

            pending = (
                FleetFileTransfer.query.filter_by(host_id=host.id, consumed_at=None)
                .order_by(FleetFileTransfer.created_at.asc())
                .all()
            )
            payload = [
                {
                    "id": file.id,
                    "filename": file.filename,
                    "size": file.size_bytes,
                }
                for file in pending
            ]
            return jsonify(payload)

    @ingest_app.get("/files/<int:file_id>/download")
    def download_file(file_id: int):
        api_key = request.headers.get("X-API-Key")
        agent_id = (request.headers.get("X-Agent-ID") or "").strip()
        if not api_key or not agent_id:
            return _error("Missing API key or agent identifier.", 400)
        with ingest_app.app_context():
            api_key_entry = _find_api_key(api_key)
            if not api_key_entry:
                return _error("Invalid or expired API key.", 401)
            host = _resolve_host(agent_id)
            if not host:
                return _error("Unknown agent.", 404)
            from app.models import FleetFileTransfer

            transfer = FleetFileTransfer.query.get_or_404(file_id)
            if transfer.host_id != host.id:
                return _error("File does not belong to this agent.", 403)
            if not os.path.exists(transfer.stored_path):
                return _error("File no longer available.", 404)
            transfer.consumed_at = datetime.utcnow()
            db.session.commit()
            with open(transfer.stored_path, "rb") as fh:
                data = fh.read()
            response = ingest_app.response_class(data, mimetype=transfer.mime_type or "application/octet-stream")
            response.headers["Content-Disposition"] = f"attachment; filename={transfer.filename}"
            return response

    def _auth_agent_request():
        api_key = request.headers.get("X-API-Key")
        agent_id = (
            request.headers.get("X-Agent-ID")
            or request.args.get("agent")
            or (request.get_json(silent=True) or {}).get("agentId")
        )
        if not api_key or not agent_id:
            return None, _error("Missing API key or agent identifier.", 401)
        api_key_entry = _find_api_key(api_key)
        if not api_key_entry:
            return None, _error("Invalid or expired API key.", 401)
        host = _resolve_host(agent_id)
        if not host:
            return None, _error("Unknown agent.", 404)
        return host, None


    return ingest_app


def start_fleet_ingest_server(main_app):
    if not main_app.config.get("FLEET_INGEST_ENABLED", True):
        return
    if main_app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return
    if "fleet_ingest_server" in main_app.extensions:
        return

    ingest_app = create_fleet_ingest_app(main_app)
    host = main_app.config.get("FLEET_INGEST_HOST", "0.0.0.0")
    port = int(main_app.config.get("FLEET_INGEST_PORT", 8449))
    server = make_server(host, port, ingest_app)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    main_app.logger.info("Fleet ingest server listening on %s:%s", host, port)
    main_app.extensions["fleet_ingest_server"] = server
def _normalize_host_snapshot(payload: dict) -> dict:
    """Ensure host snapshot payload contains expected keys even if agent omits them."""
    payload = payload or {}
    normalized = deepcopy(HOST_SNAPSHOT_DEFAULTS)

    for key, value in payload.items():
        if isinstance(normalized.get(key), dict) and isinstance(value, dict):
            normalized[key] = _merge_dict(normalized.get(key), value)
        else:
            normalized[key] = deepcopy(value) if isinstance(value, (dict, list)) else value

    performance = normalized.get("performance")
    if isinstance(performance, dict):
        cpu_pct = performance.get("cpuPct")
        if cpu_pct is not None:
            normalized["cpuPct"] = cpu_pct
        ram_section = performance.get("ram")
        if isinstance(ram_section, dict):
            normalized["ram"] = _merge_dict(normalized.get("ram"), ram_section)

    storage = normalized.get("storage")
    if isinstance(storage, dict):
        disk_section = storage.get("disk")
        if isinstance(disk_section, dict):
            normalized["disk"] = _merge_dict(normalized.get("disk"), disk_section)

    security = normalized.get("security")
    if isinstance(security, dict):
        firewall = security.get("firewall")
        if isinstance(firewall, dict):
            normalized["firewall"] = _merge_dict(normalized.get("firewall"), firewall)
            normalized["firewallDomain"] = firewall.get("domain")
            normalized["firewallPrivate"] = firewall.get("privateProfile")
            normalized["firewallPublic"] = firewall.get("publicProfile")
        antivirus = security.get("antivirus")
        if isinstance(antivirus, dict):
            normalized["antivirus"] = _merge_dict(normalized.get("antivirus"), antivirus)

    events = normalized.get("events")
    if isinstance(events, dict):
        normalized["events"] = _merge_dict(HOST_SNAPSHOT_DEFAULTS.get("events"), events)

    updates = normalized.get("updates")
    if isinstance(updates, dict):
        normalized["updates"] = _merge_dict(HOST_SNAPSHOT_DEFAULTS.get("updates"), updates)

    network = normalized.get("network")
    if isinstance(network, dict):
        normalized["network"] = _merge_dict(HOST_SNAPSHOT_DEFAULTS.get("network"), network)

    firewall_section = normalized.get("firewall")
    if isinstance(firewall_section, dict) and firewall_section.get("anyProfileEnabled") is None:
        firewall_section["anyProfileEnabled"] = any(
            firewall_section.get(flag) for flag in ("domain", "privateProfile", "publicProfile")
        )

    return normalized
