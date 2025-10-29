# -*- coding: utf-8 -*-
"""
Backup Monitor blueprint routes.
Provides CRUD operations for LTO tape cartridges, backup jobs, storage locations,
custody events, and auditing for Helpdesk Pro.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable, Optional

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
)
from flask_login import login_required, current_user
from flask_babel import gettext as _

from app import db
from app.models import (
    TapeCartridge,
    BackupJob,
    TapeLocation,
    TapeCustodyEvent,
    BackupAuditLog,
    BackupJobTape,
    User,
)
from app.permissions import get_module_access, require_module_write

backup_bp = Blueprint("backup", __name__)


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

VERIFY_RESULT_CHOICES = [
    ("pending", _("Pending")),
    ("success", _("Success")),
    ("failed", _("Failed")),
]

TAPE_STATUS_VALUES = {value for value, _ in TAPE_STATUS_CHOICES}
LOCATION_TYPE_VALUES = {value for value, _ in LOCATION_TYPE_CHOICES}
VERIFY_RESULT_VALUES = {value for value, _ in VERIFY_RESULT_CHOICES}


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
    tapes = TapeCartridge.query.order_by(TapeCartridge.barcode.asc()).all()
    jobs = BackupJob.query.order_by(BackupJob.job_date.desc()).limit(100).all()
    users = User.query.filter_by(active=True).order_by(User.username.asc()).all()

    status_summary = Counter(tape.status or "unknown" for tape in tapes)
    location_summary = Counter(
        (tape.current_location.location_type if tape.current_location else "unassigned")
        for tape in tapes
    )

    module_access = get_module_access(current_user, "backup")
    return render_template(
        "backup/monitor.html",
        tapes=tapes,
        jobs=jobs,
        users=users,
        module_access=module_access,
        status_summary=status_summary,
        location_summary=location_summary,
        tape_status_choices=TAPE_STATUS_CHOICES,
        location_type_choices=LOCATION_TYPE_CHOICES,
        verify_result_choices=VERIFY_RESULT_CHOICES,
    )


@backup_bp.route("/backup/tapes/<int:tape_id>")
@login_required
def tape_detail(tape_id: int):
    tape = TapeCartridge.query.get_or_404(tape_id)
    module_access = get_module_access(current_user, "backup")
    related_jobs = [jt.job for jt in tape.tape_jobs]
    audit_entries = (
        BackupAuditLog.query.filter(BackupAuditLog.entity_type == "tape", BackupAuditLog.entity_id == tape.id)
        .order_by(BackupAuditLog.created_at.desc())
        .limit(100)
        .all()
    )
    return render_template(
        "backup/tape_detail.html",
        tape=tape,
        module_access=module_access,
        tape_status_choices=TAPE_STATUS_CHOICES,
        location_type_choices=LOCATION_TYPE_CHOICES,
        verify_result_choices=VERIFY_RESULT_CHOICES,
        jobs=related_jobs,
        audit_entries=audit_entries,
    )


@backup_bp.route("/backup/jobs/<int:job_id>")
@login_required
def job_detail(job_id: int):
    job = BackupJob.query.get_or_404(job_id)
    module_access = get_module_access(current_user, "backup")
    audit_entries = (
        BackupAuditLog.query.filter(BackupAuditLog.entity_type == "job", BackupAuditLog.entity_id == job.id)
        .order_by(BackupAuditLog.created_at.desc())
        .limit(100)
        .all()
    )
    tapes = TapeCartridge.query.order_by(TapeCartridge.barcode.asc()).all()
    users = User.query.filter_by(active=True).order_by(User.username.asc()).all()
    return render_template(
        "backup/job_detail.html",
        job=job,
        module_access=module_access,
        tapes=tapes,
        users=users,
        verify_result_choices=VERIFY_RESULT_CHOICES,
        audit_entries=audit_entries,
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
        flash(_("A tape with this barcode already exists."), "danger")
        return redirect(url_for("backup.monitor"))

    status = _clean_str("status") or "empty"
    if status not in TAPE_STATUS_VALUES:
        status = "empty"

    tape = TapeCartridge(
        barcode=barcode,
        lto_generation=_clean_str("lto_generation") or "LTO-9",
        nominal_capacity_tb=_parse_decimal("nominal_capacity_tb"),
        usable_capacity_tb=_parse_decimal("usable_capacity_tb"),
        status=status,
        notes=_clean_str("notes"),
    )
    tape.set_usage_tags(_parse_tags(request.form.get("usage_tags")))
    inventory_date = _parse_datetime("last_inventory_at")
    if inventory_date:
        tape.last_inventory_at = inventory_date

    db.session.add(tape)
    db.session.flush()
    _record_audit("tape", tape.id, "create", None, f"Created tape {tape.barcode}")
    db.session.commit()
    flash(_("Tape cartridge “%(barcode)s” created.", barcode=tape.barcode), "success")
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

    if not changes:
        flash(_("No changes detected for the tape."), "info")
        return redirect(request.referrer or url_for("backup.tape_detail", tape_id=tape.id))

    db.session.add(tape)
    for field, old_val, new_val in changes:
        _record_audit("tape", tape.id, field, str(old_val) if old_val is not None else None, str(new_val) if new_val is not None else None)
    db.session.commit()
    flash(_("Tape cartridge updated."), "success")
    return redirect(request.referrer or url_for("backup.tape_detail", tape_id=tape.id))


@backup_bp.route("/backup/jobs", methods=["POST"])
@login_required
def create_job():
    require_module_write("backup")
    name = _clean_str("name")
    if not name:
        flash(_("Job name is required."), "warning")
        return redirect(url_for("backup.monitor"))

    retention = _parse_int("retention_days") or 30
    job_date = _parse_datetime("job_date") or datetime.utcnow()

    verify_result = _clean_str("verify_result")
    if verify_result not in VERIFY_RESULT_VALUES:
        verify_result = None

    job = BackupJob(
        name=name,
        job_date=job_date,
        retention_days=retention,
        total_files=_parse_int("total_files"),
        total_size_bytes=_parse_int("total_size_bytes"),
        verify_result=verify_result,
        source_system=_clean_str("source_system"),
        responsible_user_id=_parse_int("responsible_user_id"),
        notes=_clean_str("notes"),
    )
    job.sync_expiration()
    db.session.add(job)
    tape_ids = request.form.getlist("tape_ids")
    _apply_job_tape_membership(job, tape_ids)
    db.session.flush()
    _record_audit("job", job.id, "create", None, f"Created job {job.name}")
    db.session.commit()
    flash(_("Backup job “%(name)s” created.", name=job.name), "success")
    return redirect(url_for("backup.monitor"))


@backup_bp.route("/backup/jobs/<int:job_id>/update", methods=["POST"])
@login_required
def update_job(job_id: int):
    job = BackupJob.query.get_or_404(job_id)
    require_module_write("backup")
    changes = []

    def _update(field, parser=None):
        value = request.form.get(field)
        new_val = parser(field) if parser else _clean_str(field)
        if parser in {_parse_int} and value not in (None, "") and new_val is None:
            return
        old_val = getattr(job, field)
        if new_val == old_val or (new_val is None and old_val is None):
            return
        setattr(job, field, new_val)
        changes.append((field, old_val, new_val))

    _update("name")
    _update("retention_days", _parse_int)
    _update("total_files", _parse_int)
    _update("total_size_bytes", _parse_int)
    _update("source_system")
    _update("notes")

    verify_result = _clean_str("verify_result")
    if verify_result not in VERIFY_RESULT_VALUES:
        verify_result = None
    if verify_result != job.verify_result:
        changes.append(("verify_result", job.verify_result, verify_result))
        job.verify_result = verify_result

    job_date = _parse_datetime("job_date")
    if job_date:
        changes.append(("job_date", job.job_date, job_date))
        job.job_date = job_date

    user_id = _parse_int("responsible_user_id")
    if user_id != job.responsible_user_id:
        changes.append(("responsible_user_id", job.responsible_user_id, user_id))
        job.responsible_user_id = user_id

    old_expires = job.expires_at
    job.sync_expiration()
    if old_expires != job.expires_at:
        changes.append(("expires_at", old_expires, job.expires_at))

    tape_ids = request.form.getlist("tape_ids")
    if tape_ids:
        before = [assoc.tape_id for assoc in job.job_tapes]
        after_ids = _apply_job_tape_membership(job, tape_ids)
        if before != after_ids:
            changes.append(("tape_bindings", str(before), str(after_ids)))
    else:
        if job.job_tapes:
            before = [assoc.tape_id for assoc in job.job_tapes]
            for assoc in list(job.job_tapes):
                db.session.delete(assoc)
            changes.append(("tape_bindings", str(before), "[]"))

    if not changes:
        flash(_("No changes detected for the backup job."), "info")
        return redirect(request.referrer or url_for("backup.job_detail", job_id=job.id))

    db.session.add(job)
    for field, old_val, new_val in changes:
        _record_audit(
            "job",
            job.id,
            field,
            str(old_val) if old_val is not None else None,
            str(new_val) if new_val is not None else None,
        )
    db.session.commit()
    flash(_("Backup job updated."), "success")
    return redirect(request.referrer or url_for("backup.job_detail", job_id=job.id))


def _apply_job_tape_membership(job: BackupJob, tape_ids: Iterable[str]) -> list[int]:
    valid_ids = []
    if not tape_ids:
        return valid_ids
    seen = set()
    sequence = 1
    for raw in tape_ids:
        try:
            tape_id = int(raw)
        except (TypeError, ValueError):
            continue
        if tape_id in seen:
            continue
        seen.add(tape_id)
        tape = TapeCartridge.query.get(tape_id)
        if not tape:
            continue
        assoc = next((jt for jt in job.job_tapes if jt.tape_id == tape_id), None)
        if not assoc:
            assoc = BackupJobTape(tape=tape, job=job)
            job.job_tapes.append(assoc)
        assoc.sequence = sequence
        valid_ids.append(tape_id)
        sequence += 1
    # Remove stale associations
    for assoc in list(job.job_tapes):
        if assoc.tape_id not in valid_ids:
            job.job_tapes.remove(assoc)
            db.session.delete(assoc)
    return valid_ids


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
    data = [
        {
            "field": entry.field_name,
            "old": entry.old_value,
            "new": entry.new_value,
            "by": entry.changed_by_username,
            "timestamp": entry.created_at.isoformat(),
            "reason": entry.reason,
        }
        for entry in entries
    ]
    return jsonify({"entries": data})
