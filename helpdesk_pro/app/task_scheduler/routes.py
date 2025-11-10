# -*- coding: utf-8 -*-
"""
Task Scheduler blueprint.
Provides task management, slot scheduling, share links, and validation helpers.
"""

from __future__ import annotations

import secrets
import re
from datetime import datetime, timedelta, timezone
from typing import List, Tuple

from zoneinfo import ZoneInfo
from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    url_for,
    current_app,
    abort,
    redirect,
)
from flask_login import login_required, current_user
from flask_babel import gettext as _
from flask_mail import Message
from sqlalchemy.orm import selectinload

from app import db
from app.models import (
    TaskSchedulerTask,
    TaskSchedulerSlot,
    TaskSchedulerShareToken,
    TaskSchedulerAuditLog,
    Ticket,
)
from app.models.user import User
from app.permissions import get_module_access
from app.mail_utils import queue_mail_with_optional_auth


task_scheduler_bp = Blueprint("task_scheduler", __name__, url_prefix="/task-scheduler")


ALLOWED_ROLES = {"admin", "manager", "technician"}
STATUS_VALUES = {"Shared", "Closed"}
ATHENS_TZ = ZoneInfo("Europe/Athens")
DURATION_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)")
TASK_TITLE_MAX = 160


def _require_role():
    if not current_user.is_authenticated:
        abort(403)
    role = (current_user.role or "").strip().lower()
    if role not in ALLOWED_ROLES:
        abort(403)


def _require_manager_access():
    if not current_user.is_authenticated:
        abort(403)
    role = (current_user.role or "").strip().lower()
    if role not in {"admin", "manager"}:
        abort(403)


def _can_manage() -> bool:
    if not current_user.is_authenticated:
        return False
    role = (current_user.role or "").strip().lower()
    return role in {"admin", "manager"}


def _restricts_to_own_tasks() -> bool:
    role = (current_user.role or "").strip().lower()
    return role in {"admin", "manager"}


def _task_scope():
    query = TaskSchedulerTask.query
    if _restricts_to_own_tasks():
        query = query.filter(TaskSchedulerTask.created_by_user_id == current_user.id)
    return query


def _get_task_or_404(task_id: int, loader_options: tuple = ()):
    query = _task_scope()
    if loader_options:
        query = query.options(*loader_options)
    return query.filter(TaskSchedulerTask.id == task_id).first_or_404()


def _get_slot_or_404(slot_id: int) -> TaskSchedulerSlot:
    slot = TaskSchedulerSlot.query.options(selectinload(TaskSchedulerSlot.task)).get_or_404(slot_id)
    if _restricts_to_own_tasks() and (not slot.task or slot.task.created_by_user_id != current_user.id):
        abort(404)
    return slot


def _get_share_token_or_404(token_id: int) -> TaskSchedulerShareToken:
    token = TaskSchedulerShareToken.query.options(selectinload(TaskSchedulerShareToken.task)).get_or_404(token_id)
    if _restricts_to_own_tasks() and (not token.task or token.task.created_by_user_id != current_user.id):
        abort(404)
    return token


def _first_active_share_token(task: TaskSchedulerTask) -> TaskSchedulerShareToken | None:
    for token in task.share_tokens:
        if token.is_active():
            return token
    query = TaskSchedulerShareToken.query.filter_by(task_id=task.id)
    for token in query:
        if token.is_active():
            return token
    return None


def _json_response(success: bool, message: str, status: int = 200, **extra):
    payload = {"success": success, "message": message}
    payload.update(extra)
    return jsonify(payload), status


def _normalise_duration(raw: str) -> Tuple[str, int, int]:
    cleaned = (raw or "").strip()
    normalized = cleaned or "1-2 hours"
    tokenised = [t.replace(",", ".") for t in DURATION_PATTERN.findall(normalized.replace("–", "-"))]
    numbers: List[float] = []
    for token in tokenised[:2]:
        try:
            numbers.append(float(token))
        except ValueError:
            continue
    if not numbers:
        numbers = [1.0]
    if len(numbers) == 1:
        min_hours = max_hours = numbers[0]
    else:
        min_hours, max_hours = sorted(numbers[:2])
    min_minutes = max(15, int(min_hours * 60))
    max_minutes = max(min_minutes, int(max_hours * 60))
    return normalized, min_minutes, max_minutes


def _parse_datetime_local(raw: str):
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("%d/%m/%Y %H:%M", "%Y-%m-%dT%H:%M"):
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed.replace(tzinfo=ATHENS_TZ)
        except ValueError:
            continue
    return None


def _local_to_utc(local_dt: datetime) -> datetime:
    if local_dt.tzinfo is None:
        local_dt = local_dt.replace(tzinfo=ATHENS_TZ)
    return local_dt.astimezone(timezone.utc).replace(tzinfo=None)


def _utc_to_local(utc_dt: datetime):
    if utc_dt is None:
        return None
    return utc_dt.replace(tzinfo=timezone.utc).astimezone(ATHENS_TZ)


def _format_local(utc_dt: datetime, fmt: str = "%d/%m/%Y %H:%M") -> str:
    local_dt = _utc_to_local(utc_dt)
    if not local_dt:
        return "—"
    return local_dt.strftime(fmt)


def _task_duration_minutes(task: TaskSchedulerTask) -> int:
    if task.estimated_duration_minutes_max:
        return task.estimated_duration_minutes_max
    if task.estimated_duration_minutes_min:
        return task.estimated_duration_minutes_min
    return 60


def _slot_conflicts(task_id: int, start_utc: datetime, duration_minutes: int, exclude_slot_id: int | None = None) -> bool:
    end_utc = start_utc + timedelta(minutes=duration_minutes)
    query = TaskSchedulerSlot.query.filter_by(task_id=task_id)
    if exclude_slot_id:
        query = query.filter(TaskSchedulerSlot.id != exclude_slot_id)
    for slot in query:
        existing_start = slot.start_at
        existing_end = existing_start + timedelta(minutes=slot.duration_minutes or duration_minutes)
        if start_utc < existing_end and end_utc > existing_start:
            return True
    return False


def _suggest_alternatives(task: TaskSchedulerTask, desired_local: datetime, duration_minutes: int) -> list[str]:
    if desired_local.tzinfo is None:
        desired_local = desired_local.replace(tzinfo=ATHENS_TZ)
    day_start = desired_local.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    busy: list[tuple[datetime, datetime]] = []
    for slot in task.slots:
        local_start = _utc_to_local(slot.start_at)
        if not local_start:
            continue
        local_end = local_start + timedelta(minutes=slot.duration_minutes or duration_minutes)
        if local_end <= day_start or local_start >= day_end:
            continue
        busy.append((local_start, local_end))
    busy.sort(key=lambda pair: pair[0])
    suggestions: list[datetime] = []
    pointer = day_start
    for start, end in busy:
        if pointer < start:
            gap_minutes = (start - pointer).total_seconds() / 60
            if gap_minutes >= duration_minutes:
                candidate = max(pointer, desired_local)
                if (start - candidate).total_seconds() / 60 >= duration_minutes:
                    suggestions.append(candidate)
        pointer = max(pointer, end)
    if pointer < day_end:
        gap_minutes = (day_end - pointer).total_seconds() / 60
        if gap_minutes >= duration_minutes:
            candidate = max(pointer, desired_local)
            suggestions.append(candidate)
    return [_format_local(option) for option in suggestions[:3]]


def _task_share_url(token: TaskSchedulerShareToken):
    base = current_app.config.get("BASE_URL") or request.url_root.rstrip("/")
    return f"{base}{url_for('task_scheduler.share_page', token=token.token)}"


@task_scheduler_bp.route("", methods=["GET"])
@login_required
def list_tasks():
    _require_role()
    tasks = (
        _task_scope()
        .options(
            selectinload(TaskSchedulerTask.slots),
            selectinload(TaskSchedulerTask.share_tokens),
        )
        .order_by(TaskSchedulerTask.created_at.desc())
        .all()
    )
    status_counts = {"Shared": 0, "Closed": 0}
    slot_counts: dict[int, int] = {}
    total_slots = 0
    active_share_links = 0
    for task in tasks:
        status_counts[task.status] = status_counts.get(task.status, 0) + 1
        slot_counts[task.id] = len(task.slots)
        total_slots += slot_counts[task.id]
        active_share_links += sum(1 for token in task.share_tokens if token.is_active())

    module_access = get_module_access(current_user, "task_scheduler")

    return render_template(
        "task_scheduler/list.html",
        tasks=tasks,
        status_counts=status_counts,
        slot_counts=slot_counts,
        total_slots=total_slots,
        active_share_links=active_share_links,
        module_access=module_access,
        can_admin=_can_manage(),
        format_local=_format_local,
    )


@task_scheduler_bp.route("/<int:task_id>", methods=["GET"])
@login_required
def task_detail(task_id: int):
    _require_role()
    task = _get_task_or_404(
        task_id,
        loader_options=(
            selectinload(TaskSchedulerTask.slots),
            selectinload(TaskSchedulerTask.share_tokens),
        ),
    )
    module_access = get_module_access(current_user, "task_scheduler")
    can_admin = _can_manage()
    visible_slots = task.slots if can_admin else [
        slot for slot in task.slots if slot.user_id == current_user.id
    ]
    ticket_map: dict[int, int] = {}
    collected_ticket_ids: set[int] = set()
    audit_entries = TaskSchedulerAuditLog.query.filter_by(task_id=task.id, action="slot.ticket_created").all()
    for entry in audit_entries:
        payload = entry.payload or {}
        slot_id = payload.get("slot_id")
        ticket_id = payload.get("ticket_id")
        if slot_id is None or ticket_id is None:
            continue
        try:
            slot_id_int = int(slot_id)
            ticket_id_int = int(ticket_id)
        except (TypeError, ValueError):
            continue
        ticket_map[slot_id_int] = ticket_id_int
        collected_ticket_ids.add(ticket_id_int)
    if ticket_map:
        existing_ids = {
            tid for (tid,) in db.session.query(Ticket.id).filter(Ticket.id.in_(collected_ticket_ids)).all()
        }
        ticket_map = {
            slot_id: tid for slot_id, tid in ticket_map.items() if tid in existing_ids
        }

    return render_template(
        "task_scheduler/detail.html",
        task=task,
        slots=visible_slots,
        module_access=module_access,
        can_admin=can_admin,
        format_local=_format_local,
        slot_ticket_map=ticket_map,
    )


@task_scheduler_bp.route("/save", methods=["POST"])
@login_required
def save_task():
    _require_manager_access()
    form = request.form
    task_id = form.get("task_id")
    title = (form.get("title") or "").strip()
    if not title:
        return _json_response(False, _("Title is required."), 400)
    if len(title) > TASK_TITLE_MAX:
        return _json_response(
            False,
            _("Title must be %(limit)s characters or fewer.", limit=TASK_TITLE_MAX),
            400,
        )
    description = (form.get("description") or "").strip() or None
    status = form.get("status", "Shared")
    if status not in STATUS_VALUES:
        status = "Shared"
    duration_label, min_minutes, max_minutes = _normalise_duration(form.get("estimated_duration"))

    if task_id:
        task = _get_task_or_404(int(task_id))
        task.title = title
        task.description = description
        task.status = status
        task.estimated_duration_label = duration_label
        task.estimated_duration_minutes_min = min_minutes
        task.estimated_duration_minutes_max = max_minutes
        task.updated_by_user_id = current_user.id
        action = "task.updated"
        message = _("Task updated successfully.")
    else:
        task = TaskSchedulerTask(
            title=title,
            description=description,
            status=status,
            estimated_duration_label=duration_label,
            estimated_duration_minutes_min=min_minutes,
            estimated_duration_minutes_max=max_minutes,
            created_by_user_id=current_user.id,
            updated_by_user_id=current_user.id,
        )
        db.session.add(task)
        action = "task.created"
        message = _("Task created successfully.")

    db.session.flush()
    TaskSchedulerAuditLog.record(
        task_id=task.id,
        action=action,
        actor_id=current_user.id,
        payload={
            "title": task.title,
            "status": task.status,
            "duration": task.estimated_duration_label,
        },
    )
    db.session.commit()
    return _json_response(True, message, task_id=task.id)


@task_scheduler_bp.route("/<int:task_id>/delete", methods=["POST"])
@login_required
def delete_task(task_id: int):
    _require_manager_access()
    task = _get_task_or_404(task_id)
    TaskSchedulerAuditLog.record(
        task_id=task.id,
        action="task.deleted",
        actor_id=current_user.id,
        payload={"title": task.title},
    )
    db.session.delete(task)
    db.session.commit()
    return _json_response(True, _("Task deleted."))


def _prepare_slot_payload(task: TaskSchedulerTask, display_name: str | None, start_raw: str | None, comment: str | None):
    display = (display_name or "").strip()
    if not display:
        return None, _("Username is required.")
    local_dt = _parse_datetime_local(start_raw or "")
    if not local_dt:
        return None, _("Invalid date/time. Use dd/MM/yyyy HH:mm.")
    if task.status == "Closed":
        return None, _("This task is closed and no longer accepts bookings.")
    duration_minutes = _task_duration_minutes(task)
    start_utc = _local_to_utc(local_dt)
    if _slot_conflicts(task.id, start_utc, duration_minutes):
        suggestions = _suggest_alternatives(task, local_dt, duration_minutes)
        return None, {
            "message": _("Selected slot overlaps with an existing booking."),
            "suggestions": suggestions,
        }
    payload = {
        "display_name": display,
        "start_local": local_dt,
        "start_utc": start_utc,
        "duration_minutes": duration_minutes,
        "comment": (comment or "").strip() or None,
    }
    return payload, None


@task_scheduler_bp.route("/<int:task_id>/slots", methods=["POST"])
@login_required
def add_slot(task_id: int):
    _require_manager_access()
    task = _get_task_or_404(
        task_id,
        loader_options=(selectinload(TaskSchedulerTask.slots),),
    )
    payload, error = _prepare_slot_payload(
        task,
        request.form.get("username"),
        request.form.get("start_at"),
        request.form.get("comment"),
    )
    if not payload:
        if isinstance(error, dict):
            return _json_response(False, error["message"], 409, suggestions=error.get("suggestions", []))
        return _json_response(False, error or _("Unable to schedule slot."), 400)

    slot = TaskSchedulerSlot(
        task_id=task.id,
        display_name=payload["display_name"],
        start_at=payload["start_utc"],
        duration_minutes=payload["duration_minutes"],
        comment=payload["comment"],
        created_via="admin",
        user_id=None,
        created_by_user_id=current_user.id,
    )
    db.session.add(slot)
    db.session.flush()
    TaskSchedulerAuditLog.record(
        task_id=task.id,
        action="slot.created",
        actor_id=current_user.id,
        payload={
            "slot_id": slot.id,
            "display_name": slot.display_name,
            "start_at": slot.start_at.isoformat(),
        },
    )
    db.session.commit()
    return _json_response(True, _("Slot added successfully."))


@task_scheduler_bp.route("/slots/<int:slot_id>/delete", methods=["POST"])
@login_required
def delete_slot(slot_id: int):
    _require_manager_access()
    slot = _get_slot_or_404(slot_id)
    task_id = slot.task_id
    TaskSchedulerAuditLog.record(
        task_id=task_id,
        action="slot.deleted",
        actor_id=current_user.id,
        payload={"slot_id": slot.id, "display_name": slot.display_name},
    )
    db.session.delete(slot)
    db.session.commit()
    return _json_response(True, _("Slot removed."))


@task_scheduler_bp.route("/slots/<int:slot_id>/ticket", methods=["POST"])
@login_required
def slot_create_ticket(slot_id: int):
    _require_manager_access()
    slot = _get_slot_or_404(slot_id)
    task = slot.task
    display_name = slot.display_name or _("Unnamed user")
    subject = f"[{slot.id:04d}] {display_name} + {task.title}"
    slot_local = _format_local(slot.start_at)
    description_parts: list[str] = []
    if task.description:
        description_parts.append(task.description.strip())
    description_parts.append(
        _("Requested slot by %(name)s on %(start)s (duration %(duration)s).", name=display_name, start=slot_local, duration=task.estimated_duration_label or _("n/a"))
    )
    if slot.comment:
        description_parts.append(_("User comment: %(comment)s", comment=slot.comment))
    description = "\n\n".join(description_parts)
    actor_role = (current_user.role or "").strip().lower()
    department_value = (current_user.department or "").strip() or None
    if actor_role == "manager" and not department_value:
        return _json_response(False, _("Managers must belong to a department before creating tickets."), 400)
    try:
        ticket = Ticket(
            subject=subject,
            description=description,
            priority="Low",
            status="Open",
            department=department_value,
            created_by=current_user.id,
        )
        db.session.add(ticket)
        db.session.flush()
        TaskSchedulerAuditLog.record(
            task_id=task.id,
            action="slot.ticket_created",
            actor_id=current_user.id,
            payload={"slot_id": slot.id, "ticket_id": ticket.id},
        )
        db.session.commit()
    except Exception as exc:  # pragma: no cover - defensive
        current_app.logger.exception("Failed to create ticket from slot %s", slot_id)
        db.session.rollback()
        return _json_response(False, _("Unable to create ticket."), 400)
    ticket_url = url_for("tickets.view_ticket", id=ticket.id)
    return _json_response(True, _("Ticket created successfully."), ticket_id=ticket.id, ticket_url=ticket_url)


@task_scheduler_bp.route("/<int:task_id>/slots/options", methods=["GET"])
@login_required
def slot_options(task_id: int):
    _require_manager_access()
    task = _get_task_or_404(
        task_id,
        loader_options=(selectinload(TaskSchedulerTask.slots),),
    )
    options = [
        {"id": slot.id, "label": f"{slot.display_name} — {_format_local(slot.start_at)}"}
        for slot in task.slots
    ]
    return jsonify({"success": True, "options": options})


@task_scheduler_bp.route("/<int:task_id>/slots/check", methods=["GET"])
@login_required
def slot_check(task_id: int):
    _require_role()
    task = _get_task_or_404(
        task_id,
        loader_options=(selectinload(TaskSchedulerTask.slots),),
    )
    local_dt = _parse_datetime_local(request.args.get("start_at", ""))
    if not local_dt:
        return _json_response(False, _("Invalid date/time."), 400)
    duration = _task_duration_minutes(task)
    start_utc = _local_to_utc(local_dt)
    if _slot_conflicts(task.id, start_utc, duration):
        return _json_response(
            False,
            _("Slot is already taken."),
            409,
            suggestions=_suggest_alternatives(task, local_dt, duration),
        )
    return _json_response(True, _("Slot is available."))


@task_scheduler_bp.route("/<int:task_id>/share", methods=["POST"])
@login_required
def create_share(task_id: int):
    _require_manager_access()
    task = _get_task_or_404(task_id)
    visibility = request.form.get("visibility", "public")
    if visibility not in {"public", "restricted"}:
        visibility = "public"
    expires_raw = request.form.get("expires_at")
    expires_local = _parse_datetime_local(expires_raw) if expires_raw else None
    expires_utc = _local_to_utc(expires_local) if expires_local else None

    token_value = secrets.token_urlsafe(24).replace("-", "").replace("_", "")
    token = TaskSchedulerShareToken(
        task_id=task.id,
        token=token_value,
        visibility=visibility,
        expires_at=expires_utc,
        created_by_user_id=current_user.id,
    )
    db.session.add(token)
    db.session.flush()
    TaskSchedulerAuditLog.record(
        task_id=task.id,
        action="share.created",
        actor_id=current_user.id,
        payload={
            "token_id": token.id,
            "visibility": visibility,
            "expires_at": token.expires_at.isoformat() if token.expires_at else None,
        },
    )
    db.session.commit()
    return _json_response(True, _("Share link created."), link=_task_share_url(token))


@task_scheduler_bp.route("/share/<int:token_id>/revoke", methods=["POST"])
@login_required
def revoke_share(token_id: int):
    _require_manager_access()
    token = _get_share_token_or_404(token_id)
    token.revoked_at = datetime.utcnow()
    TaskSchedulerAuditLog.record(
        task_id=token.task_id,
        action="share.revoked",
        actor_id=current_user.id,
        payload={"token_id": token.id},
    )
    db.session.commit()
    return _json_response(True, _("Share link revoked."))


@task_scheduler_bp.route("/email/recipients", methods=["GET"])
@login_required
def email_recipients():
    _require_manager_access()
    users = (
        User.query.filter(User.active.is_(True), User.email.isnot(None))
        .order_by(User.full_name.asc(), User.username.asc())
        .all()
    )
    options = [
        {
            "id": user.id,
            "label": user.display_name,
            "email": user.email,
        }
        for user in users
    ]
    return jsonify({"success": True, "options": options})


def _resolve_share_token(token_value: str) -> TaskSchedulerShareToken:
    token = TaskSchedulerShareToken.query.options(
        selectinload(TaskSchedulerShareToken.task).selectinload(TaskSchedulerTask.slots)
    ).filter_by(token=token_value).first()
    if not token:
        abort(404)
    return token


@task_scheduler_bp.route("/share/<string:token>", methods=["GET"])
def share_page(token: str):
    share_token = _resolve_share_token(token)
    if not share_token.is_active():
        return render_template("task_scheduler/public_share.html", share_token=share_token, task=share_token.task, format_local=_format_local, inactive_message=_("This link is no longer available."))
    if share_token.visibility == "restricted" and not current_user.is_authenticated:
        return redirect(url_for("auth.login", next=request.url))
    return render_template(
        "task_scheduler/public_share.html",
        share_token=share_token,
        task=share_token.task,
        format_local=_format_local,
        inactive_message=None,
    )


def _handle_public_slot(share_token: TaskSchedulerShareToken, form):
    task = share_token.task
    payload, error = _prepare_slot_payload(task, form.get("username"), form.get("start_at"), form.get("comment"))
    if not payload:
        if isinstance(error, dict):
            return None, error
        return None, {"message": error}
    linked_user_id = current_user.id if (share_token.visibility == "restricted" and current_user.is_authenticated) else None
    created_via = "share_public" if share_token.visibility == "public" else "share_auth"
    slot = TaskSchedulerSlot(
        task_id=task.id,
        display_name=payload["display_name"],
        start_at=payload["start_utc"],
        duration_minutes=payload["duration_minutes"],
        comment=payload["comment"],
        created_via=created_via,
        created_by_user_id=linked_user_id,
        user_id=linked_user_id,
    )
    db.session.add(slot)
    db.session.flush()
    TaskSchedulerAuditLog.record(
        task_id=task.id,
        action="slot.shared",
        actor_id=linked_user_id,
        payload={
            "slot_id": slot.id,
            "display_name": slot.display_name,
            "token_id": share_token.id,
        },
    )
    db.session.commit()
    return slot, None


@task_scheduler_bp.route("/share/<string:token>/slots", methods=["POST"])
def share_slot_create(token: str):
    share_token = _resolve_share_token(token)
    if not share_token.is_active():
        return _json_response(False, _("Link is no longer active."), 410)
    if share_token.visibility == "restricted" and not current_user.is_authenticated:
        return _json_response(False, _("You must sign in to use this link."), 403)
    slot, error = _handle_public_slot(share_token, request.form)
    if not slot:
        return _json_response(False, error.get("message", _("Could not schedule slot.")), 409, suggestions=error.get("suggestions", []))
    return _json_response(True, _("Your time slot is confirmed."), slot={
        "name": slot.display_name,
        "start_at": _format_local(slot.start_at),
        "duration": slot.duration_minutes,
    })


@task_scheduler_bp.route("/share/<string:token>/check", methods=["GET"])
def share_slot_check(token: str):
    share_token = _resolve_share_token(token)
    task = share_token.task
    local_dt = _parse_datetime_local(request.args.get("start_at", ""))
    if not local_dt:
        return _json_response(False, _("Invalid date/time."), 400)
    duration = _task_duration_minutes(task)
    start_utc = _local_to_utc(local_dt)
    if _slot_conflicts(task.id, start_utc, duration):
        return _json_response(
            False,
            _("Slot is already taken."),
            409,
            suggestions=_suggest_alternatives(task, local_dt, duration),
        )
    if task.status == "Closed":
        return _json_response(False, _("This task is closed."), 409)
    if not share_token.is_active():
        return _json_response(False, _("Link is no longer active."), 410)
    return _json_response(True, _("Slot is available."))


@task_scheduler_bp.route("/<int:task_id>/email", methods=["POST"])
@login_required
def email_task(task_id: int):
    _require_manager_access()
    task = _get_task_or_404(
        task_id,
        loader_options=(selectinload(TaskSchedulerTask.share_tokens),),
    )
    share_token = _first_active_share_token(task)
    if not share_token:
        return _json_response(False, _("Generate a share link before emailing this task."), 400)
    scope = request.form.get("scope", "custom")
    recipient_ids = request.form.getlist("recipients[]") or request.form.getlist("recipients")
    recipient_ids = [rid for rid in recipient_ids if rid]
    query = User.query.filter(User.active.is_(True), User.email.isnot(None))
    if scope == "all":
        selected_users = query.all()
    else:
        ids: list[int] = []
        for raw in recipient_ids:
            try:
                ids.append(int(raw))
            except (TypeError, ValueError):
                continue
        if not ids:
            return _json_response(False, _("Select at least one recipient."), 400)
        selected_users = query.filter(User.id.in_(ids)).all()
    if not selected_users:
        return _json_response(False, _("No recipients available for this task."), 400)
    link = _task_share_url(share_token)
    note = (request.form.get("message") or "").strip()
    subject = _("Task update: %(title)s", title=task.title)
    base_body = [
        _("You are invited to review the task \"%(title)s\".", title=task.title),
    ]
    if note:
        base_body.append("")
        base_body.append(note)
    base_body.extend(
        [
            "",
            _("Open task link: %(link)s", link=link),
        ]
    )
    body = "\n".join(base_body)
    recipients = [user.email for user in selected_users]
    sender = current_app.config.get("MAIL_DEFAULT_SENDER") or current_app.config.get("MAIL_USERNAME")
    if not sender:
        return _json_response(False, _("Email sending is not configured."), 500)
    message = Message(
        subject=subject,
        recipients=recipients,
        sender=sender,
        body=body,
    )
    queue_mail_with_optional_auth(message, description=f"task {task.id} share email")
    TaskSchedulerAuditLog.record(
        task_id=task.id,
        action="task.email_sent",
        actor_id=current_user.id,
        payload={
            "recipient_ids": [user.id for user in selected_users],
            "share_token_id": share_token.id,
        },
    )
    db.session.commit()
    return _json_response(True, _("Task link emailed successfully."))


__all__ = [
    "task_scheduler_bp",
]
