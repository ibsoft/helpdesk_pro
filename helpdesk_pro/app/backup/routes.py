# -*- coding: utf-8 -*-
"""
Backup Monitor blueprint routes.
Provides CRUD operations for removable storage media (tapes & disks), storage
locations, custody events, and auditing for Helpdesk Pro.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    abort,
)
from flask_login import login_required, current_user
from flask_babel import gettext as _

from app import db
from app.models import (
    TapeCartridge,
    TapeLocation,
    TapeCustodyEvent,
    BackupAuditLog,
)
from app.permissions import get_module_access, require_module_write

backup_bp = Blueprint("backup", __name__)


@backup_bp.route("/backup/lto-barcode", methods=["GET"])
@login_required
def lto_barcode_generator():
    access = get_module_access(current_user, "backup")
    if not access:
        abort(403)
    return render_template("backup/lto_barcode.html")


TAPE_STATUS_CHOICES = [
    ("empty", _("Empty")),
    ("in_use", _("In Use")),
    ("full", _("Full")),
    ("pending_destruction", _("Pending Destruction")),
]

LOCATION_TYPE_CHOICES = [
    ("on_site", _("On-Site")),
    ("in_transit", _("In Transit")),
    ("off_site", _("Off-Site")),
]

TAPE_STATUS_VALUES = {value for value, _ in TAPE_STATUS_CHOICES}
LOCATION_TYPE_VALUES = {value for value, _ in LOCATION_TYPE_CHOICES}
STATUS_LABELS = {key: label for key, label in TAPE_STATUS_CHOICES}
LOCATION_LABELS = {key: label for key, label in LOCATION_TYPE_CHOICES}
LIFECYCLE_POLICY_CHOICES = [
    ("daily", _("Daily")),
    ("weekly", _("Weekly")),
    ("monthly", _("Monthly")),
]
LIFECYCLE_POLICY_VALUES = {value for value, _ in LIFECYCLE_POLICY_CHOICES}
LIFECYCLE_POLICY_LABELS = {key: label for key, label in LIFECYCLE_POLICY_CHOICES}


def _clean_str(field: str) -> Optional[str]:
    value = request.form.get(field)
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _parse_int(field: str) -> Optional[int]:
    value = _clean_str(field)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_decimal(field: str) -> Optional[Decimal]:
    value = _clean_str(field)
    if value is None:
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return None


def _parse_datetime(field: str) -> Optional[datetime]:
    value = _clean_str(field)
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(value, fmt)
            if fmt == "%Y-%m-%d":
                return datetime(parsed.year, parsed.month, parsed.day, 0, 0, 0)
            return parsed
        except ValueError:
            continue
    return None


def _parse_tags(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    return [token.strip() for token in raw.split(",") if token.strip()]


def _normalise_lifecycle_value(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if value not in LIFECYCLE_POLICY_VALUES:
        return None
    return value


def _value_is_blank(value: Optional[str]) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() in {"", "None", "null"}:
        return True
    return False


def _describe_location(location_id: Optional[str]) -> str:
    if _value_is_blank(location_id):
        return _("Unassigned")
    try:
        numeric_id = int(location_id)
    except (TypeError, ValueError):
        return str(location_id)
    location = db.session.get(TapeLocation, numeric_id)
    if not location:
        return str(location_id)
    loc_label = LOCATION_LABELS.get(location.location_type, location.location_type.replace("_", " ").title())
    details = [part for part in (
        location.site_name,
        location.shelf_code,
        location.locker_code,
        location.custody_holder,
    ) if part]
    if details:
        return f"{loc_label} ({', '.join(details)})"
    return loc_label


def _describe_status(value: Optional[str]) -> str:
    if _value_is_blank(value):
        return _("—")
    return STATUS_LABELS.get(value, value.replace("_", " ").title())


def _describe_medium_type(value: Optional[str]) -> str:
    if _value_is_blank(value):
        return _("—")
    if value == "disk":
        return _("External Disk")
    if value == "tape":
        return _("Tape Cartridge")
    return value.replace("_", " ").title()


def _describe_retention_days(value: Optional[str]) -> str:
    if _value_is_blank(value):
        return _("Not set")
    return _("%(days)s day(s)", days=value)


def _describe_timestamp(value: Optional[str]) -> str:
    if _value_is_blank(value):
        return _("—")
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


def _friendly_field_label(field_name: Optional[str]) -> str:
    if not field_name:
        return _("Event")
    mapping = {
        "create": _("Event"),
        "current_location_id": _("Current location"),
        "status": _("Status"),
        "lifecycle_policy": _("Lifecycle policy"),
        "usage_tags": _("Usage tags"),
        "notes": _("Notes"),
        "medium_type": _("Medium type"),
        "lto_generation": _("Generation / Model"),
        "serial_number": _("Serial number"),
        "manufacturer": _("Manufacturer"),
        "model_name": _("Model"),
        "retention_days": _("Retention (days)"),
        "retention_start_at": _("Retention start"),
        "retention_until": _("Retention end"),
        "last_inventory_at": _("Last inventory check"),
    }
    return mapping.get(field_name, field_name.replace("_", " ").title())


def _format_audit_value(field_name: Optional[str], value: Optional[str]) -> str:
    if field_name == "current_location_id":
        return _describe_location(value)
    if field_name == "status":
        return _describe_status(value)
    if field_name == "medium_type":
        return _describe_medium_type(value)
    if field_name == "lifecycle_policy":
        if _value_is_blank(value):
            return _("—")
        return LIFECYCLE_POLICY_LABELS.get(value, value.title())
    if field_name in {"retention_days"}:
        if _value_is_blank(value):
            return _("Not set")
        return _("%(days)s day(s)", days=value)
    if field_name in {"retention_start_at", "retention_until", "last_inventory_at"}:
        return _describe_timestamp(value)
    if field_name == "usage_tags":
        if _value_is_blank(value):
            return _("—")
        return value
    if _value_is_blank(value):
        return _("—")
    return value


def _present_audit_entry(entry: BackupAuditLog) -> dict[str, str]:
    field_name = entry.field_name
    field_label = _friendly_field_label(field_name)
    old_display = _format_audit_value(field_name, entry.old_value)
    new_display = _format_audit_value(field_name, entry.new_value)
    timestamp = entry.created_at.strftime("%Y-%m-%d %H:%M") if entry.created_at else "—"
    actor = entry.changed_by_username or _("—")
    return {
        "timestamp": timestamp,
        "field": field_label,
        "old": old_display,
        "new": new_display,
        "by": actor,
    }


def _respond(success: bool, message: str, category: str, redirect_url: str):
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        status = 200 if success else 400
        return jsonify(success=success, message=message, category=category), status
    flash(message, category)
    return redirect(redirect_url)


def _record_audit(
    entity_type: str,
    entity_id: int,
    field_name: Optional[str],
    old_value: Optional[str],
    new_value: Optional[str],
    reason: Optional[str] = None,
) -> None:
    entry = BackupAuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        field_name=field_name,
        old_value=old_value,
        new_value=new_value,
        reason=reason,
        changed_by_user_id=current_user.id if current_user.is_authenticated else None,
        changed_by_username=getattr(current_user, "username", None),
    )
    db.session.add(entry)


@backup_bp.route("/backup")
@login_required
def monitor():
    media_items = TapeCartridge.query.order_by(TapeCartridge.barcode.asc()).all()

    status_summary = Counter(item.status or "unknown" for item in media_items)
    location_summary = Counter(
        (item.current_location.location_type if item.current_location else "unassigned")
        for item in media_items
    )
    type_summary = Counter((item.medium_type or "tape") for item in media_items)

    retention_summary = {"overdue": 0, "due_soon": 0, "ok": 0, "unset": 0}
    now = datetime.utcnow()
    for medium in media_items:
        if medium.retention_until and medium.retention_days:
            delta = medium.retention_until - now
            if delta.total_seconds() <= 0:
                retention_summary["overdue"] += 1
            elif delta.days <= 7:
                retention_summary["due_soon"] += 1
            else:
                retention_summary["ok"] += 1
        else:
            retention_summary["unset"] += 1

    attention_media = sorted(
        [
            medium
            for medium in media_items
            if medium.retention_until
            and medium.retention_days
            and (medium.retention_until <= now or (medium.retention_until - now).days <= 7)
        ],
        key=lambda item: item.retention_until or now,
    )

    module_access = get_module_access(current_user, "backup")
    return render_template(
        "backup/monitor.html",
        media=media_items,
        module_access=module_access,
        status_summary=status_summary,
        location_summary=location_summary,
        medium_type_summary=type_summary,
        retention_summary=retention_summary,
        tape_status_choices=TAPE_STATUS_CHOICES,
        location_type_choices=LOCATION_TYPE_CHOICES,
        lifecycle_policy_choices=LIFECYCLE_POLICY_CHOICES,
        attention_media=attention_media,
    )


@backup_bp.route("/backup/tapes/<int:tape_id>")
@login_required
def tape_detail(tape_id: int):
    tape = TapeCartridge.query.get_or_404(tape_id)
    module_access = get_module_access(current_user, "backup")
    audit_entries = (
        BackupAuditLog.query.filter(BackupAuditLog.entity_type == "tape", BackupAuditLog.entity_id == tape.id)
        .order_by(BackupAuditLog.created_at.desc())
        .limit(100)
        .all()
    )
    audit_rows = [_present_audit_entry(entry) for entry in audit_entries]
    retention_state = None
    if tape.retention_days and tape.retention_until:
        delta = tape.retention_until - datetime.utcnow()
        if delta.total_seconds() <= 0:
            retention_state = _("Expired")
        elif delta.days <= 7:
            retention_state = _("Due in %(days)s day(s)", days=max(delta.days, 0))
        else:
            retention_state = _("Active (%(days)s days remaining)", days=delta.days)

    return render_template(
        "backup/tape_detail.html",
        tape=tape,
        module_access=module_access,
        tape_status_choices=TAPE_STATUS_CHOICES,
        location_type_choices=LOCATION_TYPE_CHOICES,
        lifecycle_policy_choices=LIFECYCLE_POLICY_CHOICES,
        audit_entries=audit_entries,
        audit_rows=audit_rows,
        retention_state=retention_state,
    )

@backup_bp.route("/backup/tapes", methods=["POST"])
@login_required
def create_tape():
    require_module_write("backup")
    barcode = _clean_str("barcode")
    if not barcode:
        flash(_("Barcode is required."), "warning")
        return redirect(url_for("backup.monitor"))

    existing = TapeCartridge.query.filter_by(barcode=barcode).first()
    if existing:
        flash(_("A storage medium with this barcode already exists."), "danger")
        return redirect(url_for("backup.monitor"))

    medium_type = _clean_str("medium_type") or "tape"
    if medium_type not in {"tape", "disk"}:
        medium_type = "tape"

    status = _clean_str("status") or "empty"
    if status not in TAPE_STATUS_VALUES:
        status = "empty"

    lto_generation = _clean_str("lto_generation")
    if medium_type == "tape" and not lto_generation:
        lto_generation = "LTO-9"

    tape = TapeCartridge(
        barcode=barcode,
        lto_generation=lto_generation,
        medium_type=medium_type,
        serial_number=_clean_str("serial_number"),
        manufacturer=_clean_str("manufacturer"),
        model_name=_clean_str("model_name"),
        nominal_capacity_tb=_parse_decimal("nominal_capacity_tb"),
        usable_capacity_tb=_parse_decimal("usable_capacity_tb"),
        status=status,
        lifecycle_policy=_normalise_lifecycle_value(request.form.get("lifecycle_policy")),
        notes=_clean_str("notes"),
    )
    tape.set_usage_tags(_parse_tags(request.form.get("usage_tags")))
    inventory_date = _parse_datetime("last_inventory_at")
    if inventory_date:
        tape.last_inventory_at = inventory_date

    retention_days = _parse_int("retention_days")
    retention_start = _parse_datetime("retention_start_at")
    tape.retention_days = retention_days
    if retention_start:
        tape.retention_start_at = retention_start
    elif retention_days:
        tape.retention_start_at = datetime.utcnow()
    tape.sync_retention()

    db.session.add(tape)
    db.session.flush()
    _record_audit("tape", tape.id, "create", None, f"Created {tape.medium_type} {tape.barcode}")
    db.session.commit()
    flash(_("Storage medium “%(barcode)s” created.", barcode=tape.barcode), "success")
    return redirect(url_for("backup.monitor"))


@backup_bp.route("/backup/tapes/<int:tape_id>/update", methods=["POST"])
@login_required
def update_tape(tape_id: int):
    tape = TapeCartridge.query.get_or_404(tape_id)
    require_module_write("backup")
    changes = []

    def _update_field(field, parser=None, attr=None):
        nonlocal tape
        value = request.form.get(field)
        if parser:
            new_val = parser(field)
        else:
            new_val = value.strip() if value is not None else None
            if new_val == "":
                new_val = None
        target_attr = attr or field
        old_val = getattr(tape, target_attr)
        if isinstance(old_val, Decimal):
            old_compare = str(old_val)
        else:
            old_compare = old_val

        if isinstance(new_val, Decimal) and old_val is not None:
            new_compare = str(new_val)
        else:
            new_compare = new_val

        if new_val is None and old_val is None:
            return
        if new_compare == old_compare:
            return
        setattr(tape, target_attr, new_val)
        changes.append((target_attr, old_val, new_val))

    _update_field("lto_generation")
    _update_field("notes")
    _update_field("serial_number")
    _update_field("manufacturer")
    _update_field("model_name")
    lifecycle_raw = request.form.get("lifecycle_policy")
    if lifecycle_raw is not None:
        lifecycle_value = _normalise_lifecycle_value(lifecycle_raw)
        if lifecycle_value != tape.lifecycle_policy:
            changes.append(("lifecycle_policy", tape.lifecycle_policy, lifecycle_value))
            tape.lifecycle_policy = lifecycle_value

    medium_type_value = _clean_str("medium_type")
    if medium_type_value and medium_type_value in {"tape", "disk"} and medium_type_value != tape.medium_type:
        changes.append(("medium_type", tape.medium_type, medium_type_value))
        tape.medium_type = medium_type_value

    status_value = _clean_str("status")
    if status_value:
        if status_value not in TAPE_STATUS_VALUES:
            status_value = tape.status
        if status_value != tape.status:
            changes.append(("status", tape.status, status_value))
            tape.status = status_value

    capacity_nominal = _parse_decimal("nominal_capacity_tb")
    if capacity_nominal is not None or tape.nominal_capacity_tb is not None:
        old_val = tape.nominal_capacity_tb
        if str(old_val) != str(capacity_nominal):
            changes.append(("nominal_capacity_tb", old_val, capacity_nominal))
            tape.nominal_capacity_tb = capacity_nominal
    capacity_usable = _parse_decimal("usable_capacity_tb")
    if capacity_usable is not None or tape.usable_capacity_tb is not None:
        old_val = tape.usable_capacity_tb
        if str(old_val) != str(capacity_usable):
            changes.append(("usable_capacity_tb", old_val, capacity_usable))
            tape.usable_capacity_tb = capacity_usable

    new_tags = _parse_tags(request.form.get("usage_tags"))
    old_tags = tape.usage_tag_list()
    if sorted(new_tags) != sorted(old_tags):
        tape.set_usage_tags(new_tags)
        changes.append(("usage_tags", ", ".join(old_tags), ", ".join(tape.usage_tag_list())))

    inventory_date = _parse_datetime("last_inventory_at")
    if inventory_date or tape.last_inventory_at:
        old_val = tape.last_inventory_at
        if old_val != inventory_date:
            changes.append(("last_inventory_at", old_val, inventory_date))
            tape.last_inventory_at = inventory_date

    retention_updated = False
    old_retention_until = tape.retention_until

    retention_days_raw = request.form.get("retention_days")
    if retention_days_raw is not None:
        retention_days_value = _parse_int("retention_days")
        if retention_days_raw.strip() == "":
            retention_days_value = None
        if retention_days_value != tape.retention_days:
            changes.append(("retention_days", tape.retention_days, retention_days_value))
            tape.retention_days = retention_days_value
            retention_updated = True

    retention_start_raw = request.form.get("retention_start_at")
    if retention_start_raw is not None:
        retention_start_value = _parse_datetime("retention_start_at")
        if retention_start_raw.strip() == "":
            retention_start_value = None
        if retention_start_value != tape.retention_start_at:
            changes.append(("retention_start_at", tape.retention_start_at, retention_start_value))
            tape.retention_start_at = retention_start_value
            retention_updated = True

    if retention_updated:
        tape.sync_retention()
        if tape.retention_until != old_retention_until:
            changes.append(("retention_until", old_retention_until, tape.retention_until))

    if not changes:
        flash(_("No changes detected for the storage medium."), "info")
        return redirect(request.referrer or url_for("backup.tape_detail", tape_id=tape.id))

    db.session.add(tape)
    for field, old_val, new_val in changes:
        _record_audit("tape", tape.id, field, str(old_val) if old_val is not None else None, str(new_val) if new_val is not None else None)
    db.session.commit()
    flash(_("Storage medium updated."), "success")
    return redirect(request.referrer or url_for("backup.tape_detail", tape_id=tape.id))

@backup_bp.route("/backup/tapes/<int:tape_id>/locations", methods=["POST"])
@login_required
def add_location(tape_id: int):
    tape = TapeCartridge.query.get_or_404(tape_id)
    require_module_write("backup")

    location_type = _clean_str("location_type") or "on_site"
    if location_type not in LOCATION_TYPE_VALUES:
        flash(_("Invalid location type."), "danger")
        return redirect(request.referrer or url_for("backup.tape_detail", tape_id=tape.id))

    location = TapeLocation(
        tape=tape,
        location_type=location_type,
        site_name=_clean_str("site_name"),
        shelf_code=_clean_str("shelf_code"),
        locker_code=_clean_str("locker_code"),
        provider_name=_clean_str("provider_name"),
        provider_contact=_clean_str("provider_contact"),
        custody_holder=_clean_str("custody_holder"),
        custody_reference=_clean_str("custody_reference"),
        check_in_at=_parse_datetime("check_in_at"),
        check_out_at=_parse_datetime("check_out_at"),
        notes=_clean_str("notes"),
        created_by_user_id=current_user.id,
        is_current=True,
    )
    previous_location_id = tape.current_location_id
    for existing in tape.locations:
        if existing.is_current:
            existing.is_current = False
    db.session.add(location)
    db.session.flush()
    tape.current_location_id = location.id
    _record_audit(
        "location",
        location.id,
        "create",
        None,
        f"Located tape at {location.location_type}",
    )
    _record_audit(
        "tape",
        tape.id,
        "current_location_id",
        str(previous_location_id) if previous_location_id else None,
        str(location.id),
    )
    db.session.commit()
    flash(_("Location entry added."), "success")
    return redirect(request.referrer or url_for("backup.tape_detail", tape_id=tape.id))


@backup_bp.route("/backup/tapes/<int:tape_id>/custody", methods=["POST"])
@login_required
def add_custody_event(tape_id: int):
    tape = TapeCartridge.query.get_or_404(tape_id)
    require_module_write("backup")

    event = TapeCustodyEvent(
        tape=tape,
        event_type=_clean_str("event_type") or "transfer",
        event_time=_parse_datetime("event_time") or datetime.utcnow(),
        handed_over_by=_clean_str("handed_over_by"),
        handed_over_signature=_clean_str("handed_over_signature"),
        received_by=_clean_str("received_by"),
        received_signature=_clean_str("received_signature"),
        notes=_clean_str("notes"),
        created_by_user_id=current_user.id,
    )
    db.session.add(event)
    db.session.flush()
    _record_audit(
        "custody",
        event.id,
        "create",
        None,
        f"Custody event {event.event_type} recorded.",
    )
    db.session.commit()
    flash(_("Custody event recorded."), "success")
    return redirect(request.referrer or url_for("backup.tape_detail", tape_id=tape.id))


@backup_bp.route("/backup/audit/<entity_type>/<int:entity_id>")
@login_required
def audit_trail(entity_type: str, entity_id: int):
    valid_entities = {"tape", "job", "location", "custody"}
    if entity_type not in valid_entities:
        return jsonify({"error": "Invalid entity"}), 400
    entries = (
        BackupAuditLog.query.filter(
            BackupAuditLog.entity_type == entity_type,
            BackupAuditLog.entity_id == entity_id,
        )
        .order_by(BackupAuditLog.created_at.desc())
        .limit(250)
        .all()
    )
    data = []
    for entry in entries:
        friendly = _present_audit_entry(entry)
        data.append(
            {
                "field": friendly["field"],
                "old": friendly["old"],
                "new": friendly["new"],
                "by": friendly["by"],
                "timestamp": entry.created_at.isoformat() if entry.created_at else None,
                "reason": entry.reason,
            }
        )
    return jsonify({"entries": data})


@backup_bp.route("/backup/tapes/<int:tape_id>/delete", methods=["POST"])
@login_required
def delete_tape(tape_id: int):
    tape = TapeCartridge.query.get_or_404(tape_id)
    require_module_write("backup")
    barcode = tape.barcode
    try:
        db.session.delete(tape)
        db.session.commit()
        return _respond(
            True,
            _("Storage medium “%(barcode)s” deleted.", barcode=barcode),
            "success",
            url_for("backup.monitor"),
        )
    except Exception as exc:  # pragma: no cover
        db.session.rollback()
        return _respond(
            False,
            _("Failed to delete storage medium: %(error)s", error=str(exc)),
            "danger",
            url_for("backup.tape_detail", tape_id=tape_id),
        )
