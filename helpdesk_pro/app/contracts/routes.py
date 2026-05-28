# -*- coding: utf-8 -*-
"""
Contracts blueprint routes.
Provides lifecycle tracking for software, hardware, and services agreements.
"""

from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import mimetypes
import os

from dateutil.relativedelta import relativedelta
from flask import (
    Blueprint,
    abort,
    current_app,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    flash,
    send_from_directory,
)
from flask_login import login_required, current_user

from app import db
from app.models import Contract, ContractDocument, ContractUpdateHistory, User
from app.permissions import get_module_access, require_module_write
from app.utils.files import secure_filename

contracts_bp = Blueprint("contracts", __name__)

CONTRACT_TYPES = ["Software", "Hardware", "Services"]
CONTRACT_STATUSES = ["Active", "Pending", "Expiring Soon", "Expired", "Terminated", "On Hold"]
ALERT_WINDOW_DAYS = 60
CONTRACT_DOCUMENT_FIELD = "contract_pdfs"
CONTRACT_DOCUMENT_EXTENSIONS = {"pdf", "msg", "docx", "png", "jpg", "jpeg"}
CONTRACT_DOCUMENT_INLINE_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}
CONTRACT_DOCUMENT_MIME_OVERRIDES = {
    "msg": "application/vnd.ms-outlook",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _parse_date(field_name):
    value = request.form.get(field_name)
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_decimal(field_name):
    value = request.form.get(field_name)
    if value in (None, ""):
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return None


def _parse_int(field_name):
    value = request.form.get(field_name)
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_bool(field_name):
    return request.form.get(field_name) in ("1", "true", "True", "on", "yes")


def _clean_str(field_name):
    value = request.form.get(field_name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _json_or_redirect(success, message, category, redirect_endpoint):
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        status = 200 if success else 400
        return jsonify(success=success, message=message, category=category), status
    if success:
        flash(message, category)
    else:
        flash(message, category or "danger")
    return redirect(url_for(redirect_endpoint))


def _contract_snapshot(contract):
    return {
        "name": contract.name,
        "contract_type": contract.contract_type,
        "start_date": contract.start_date,
        "end_date": contract.end_date,
        "renewal_date": contract.renewal_date,
        "status": contract.status,
        "vendor": contract.vendor,
        "contract_number": contract.contract_number,
        "po_number": contract.po_number,
        "value": contract.value,
        "currency": contract.currency,
        "auto_renew": contract.auto_renew,
        "notice_period_days": contract.notice_period_days,
        "coverage_scope": contract.coverage_scope,
        "owner_id": contract.owner_id,
        "support_email": contract.support_email,
        "support_phone": contract.support_phone,
        "support_url": contract.support_url,
        "notes": contract.notes,
    }


def _add_history(contract, action, previous=None, notes=None):
    previous = previous or {}
    entry = ContractUpdateHistory(
        contract=contract,
        action=action,
        previous_start_date=previous.get("start_date"),
        previous_end_date=previous.get("end_date"),
        previous_renewal_date=previous.get("renewal_date"),
        previous_status=previous.get("status"),
        previous_value=previous.get("value"),
        previous_currency=previous.get("currency"),
        new_start_date=contract.start_date,
        new_end_date=contract.end_date,
        new_renewal_date=contract.renewal_date,
        new_status=contract.status,
        new_value=contract.value,
        new_currency=contract.currency,
        changed_by_id=current_user.id if current_user and current_user.is_authenticated else None,
        notes=notes,
    )
    db.session.add(entry)
    return entry


def _default_contract_status(contract):
    alert = contract.lifecycle_alert()
    if alert["state"].startswith("expired"):
        return "Expired"
    if alert["state"].startswith("expires_now") or alert["state"].startswith("expiring_soon"):
        return "Expiring Soon"
    return "Active"


def _same_snapshot(before, contract):
    after = _contract_snapshot(contract)
    return all(before.get(key) == after.get(key) for key in before)


def _default_next_period(contract):
    if contract.end_date:
        next_start = contract.end_date + timedelta(days=1)
    else:
        next_start = datetime.utcnow().date()

    if contract.start_date and contract.end_date and contract.end_date >= contract.start_date:
        duration = contract.end_date - contract.start_date
        next_end = next_start + duration
    else:
        next_end = next_start + relativedelta(years=1) - timedelta(days=1)

    notice_days = contract.notice_period_days if contract.notice_period_days is not None else ALERT_WINDOW_DAYS
    next_renewal = next_end - timedelta(days=max(notice_days, 0))
    return next_start, next_end, next_renewal


def _contract_upload_folder():
    folder = os.path.join(current_app.instance_path, "contracts_uploads")
    os.makedirs(folder, exist_ok=True)
    return folder


def _date_for_filename(value):
    return value.strftime("%d-%m-%Y") if value else "no-date"


def _document_extension(filename):
    return os.path.splitext(filename or "")[1].lower().lstrip(".")


def _document_mimetype(filename):
    ext = _document_extension(filename)
    if ext in CONTRACT_DOCUMENT_MIME_OVERRIDES:
        return CONTRACT_DOCUMENT_MIME_OVERRIDES[ext]
    guessed_type, _ = mimetypes.guess_type(filename or "")
    return guessed_type or "application/octet-stream"


def _format_bytes(size):
    if not size:
        return "0 bytes"
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "bytes" else f"{int(size)} bytes"
        size = size / 1024
    return f"{size:.1f} GB"


def _uploaded_file_size(file):
    if getattr(file, "content_length", None):
        return file.content_length
    stream = getattr(file, "stream", None)
    if not stream:
        return 0
    try:
        position = stream.tell()
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(position)
        return size
    except (OSError, AttributeError):
        return 0


def _contract_document_filename(contract, original_filename, start_date=None, end_date=None):
    start_date = start_date or contract.start_date
    end_date = end_date or contract.end_date
    ext = _document_extension(original_filename)
    base = f"{contract.name}_{_date_for_filename(start_date)}_{_date_for_filename(end_date)}.{ext}"
    return secure_filename(base, allow_unicode=True) or f"contract.{ext}"


def _unique_filename(folder, filename):
    root, ext = os.path.splitext(filename)
    candidate = filename
    counter = 2
    while os.path.exists(os.path.join(folder, candidate)):
        candidate = f"{root}_{counter}{ext}"
        counter += 1
    return candidate


def _save_contract_documents(contract, history_entry=None, start_date=None, end_date=None, notes=None):
    files = [
        file
        for file in request.files.getlist(CONTRACT_DOCUMENT_FIELD)
        if file and file.filename
    ]
    if not files:
        return []

    invalid_files = [
        file.filename
        for file in files
        if _document_extension(file.filename) not in CONTRACT_DOCUMENT_EXTENSIONS
    ]
    if invalid_files:
        raise ValueError("Only PDF, MSG, DOCX, PNG, JPG or JPEG contract documents are allowed.")

    max_size = current_app.config.get("CONTRACT_DOCUMENT_MAX_SIZE") or current_app.config.get("MAX_CONTENT_LENGTH")
    if max_size:
        for file in files:
            size = _uploaded_file_size(file)
            if size > max_size:
                raise ValueError(
                    f"Document “{file.filename}” is {_format_bytes(size)}. Maximum allowed size is {_format_bytes(max_size)}."
                )

    folder = _contract_upload_folder()
    saved_documents = []
    for file in files:
        original_name = file.filename or ""
        base_filename = _contract_document_filename(
            contract,
            original_name,
            start_date=start_date,
            end_date=end_date,
        )
        stored_filename = _unique_filename(folder, base_filename)
        file.save(os.path.join(folder, stored_filename))
        document = ContractDocument(
            contract=contract,
            history=history_entry,
            original_filename=original_name,
            stored_filename=stored_filename,
            display_filename=stored_filename,
            start_date=start_date or contract.start_date,
            end_date=end_date or contract.end_date,
            uploaded_by_id=current_user.id if current_user and current_user.is_authenticated else None,
            notes=notes,
        )
        db.session.add(document)
        saved_documents.append(document)
    return saved_documents


@contracts_bp.route("/contracts")
@login_required
def list_contracts():
    today = datetime.utcnow().date()
    contracts = Contract.query.order_by(Contract.end_date.asc().nullslast(), Contract.name.asc()).all()
    users = User.query.filter_by(active=True).order_by(User.username.asc()).all()

    status_summary = Counter(contract.status or "Unspecified" for contract in contracts)
    contract_alerts = {contract.id: contract.lifecycle_alert(today) for contract in contracts}
    actionable_contracts = [
        contract for contract in contracts if contract_alerts[contract.id]["needs_action"]
    ]
    expired_count = sum(
        1 for alert in contract_alerts.values() if alert["state"].startswith("expired")
    )
    expiring_soon = sum(
        1
        for alert in contract_alerts.values()
        if alert["state"].startswith("expiring") or alert["state"].startswith("expires_now")
    )
    urgent_count = sum(
        1
        for alert in contract_alerts.values()
        if alert["needs_action"] and (alert["days_until_end"] or 0) <= 14
    )

    module_access = get_module_access(current_user, "contracts")
    return render_template(
        "contracts/contract_list.html",
        contracts=contracts,
        users=users,
        contract_types=CONTRACT_TYPES,
        contract_statuses=CONTRACT_STATUSES,
        status_summary=status_summary,
        contract_alerts=contract_alerts,
        actionable_contracts=actionable_contracts,
        expiring_soon=expiring_soon,
        expired_count=expired_count,
        urgent_count=urgent_count,
        today=today,
        module_access=module_access,
    )


@contracts_bp.route("/contracts/create", methods=["POST"])
@login_required
def create_contract():
    require_module_write("contracts")
    try:
        name = _clean_str("name")
        if not name:
            return _json_or_redirect(False, "Name is required.", "warning", "contracts.list_contracts")

        contract_type = _clean_str("contract_type")
        if contract_type not in CONTRACT_TYPES:
            return _json_or_redirect(False, "Contract type is invalid.", "warning", "contracts.list_contracts")

        contract = Contract(
            name=name,
            contract_type=contract_type,
            status=_clean_str("status"),
            vendor=_clean_str("vendor"),
            contract_number=_clean_str("contract_number"),
            po_number=_clean_str("po_number"),
            value=_parse_decimal("value"),
            currency=_clean_str("currency"),
            auto_renew=_parse_bool("auto_renew"),
            notice_period_days=_parse_int("notice_period_days"),
            coverage_scope=_clean_str("coverage_scope"),
            start_date=_parse_date("start_date"),
            end_date=_parse_date("end_date"),
            renewal_date=_parse_date("renewal_date"),
            owner_id=_parse_int("owner_id"),
            support_email=_clean_str("support_email"),
            support_phone=_clean_str("support_phone"),
            support_url=_clean_str("support_url"),
            notes=_clean_str("notes"),
        )
        if not contract.status:
            contract.status = _default_contract_status(contract)

        db.session.add(contract)
        history_entry = _add_history(contract, "created", notes="Initial contract record.")
        _save_contract_documents(contract, history_entry=history_entry, notes="Initial contract document.")
        db.session.commit()
        return _json_or_redirect(True, f"Contract “{contract.name}” added.", "success", "contracts.list_contracts")
    except Exception as exc:
        db.session.rollback()
        return _json_or_redirect(False, f"Failed to add contract: {exc}", "danger", "contracts.list_contracts")


@contracts_bp.route("/contracts/<int:contract_id>/update", methods=["POST"])
@login_required
def update_contract(contract_id):
    contract = Contract.query.get_or_404(contract_id)
    require_module_write("contracts")
    try:
        previous = _contract_snapshot(contract)
        name = _clean_str("name")
        if name:
            contract.name = name

        contract_type = _clean_str("contract_type")
        if contract_type in CONTRACT_TYPES:
            contract.contract_type = contract_type

        contract.status = _clean_str("status")
        contract.vendor = _clean_str("vendor")
        contract.contract_number = _clean_str("contract_number")
        contract.po_number = _clean_str("po_number")
        contract.value = _parse_decimal("value")
        contract.currency = _clean_str("currency")
        contract.auto_renew = _parse_bool("auto_renew")
        contract.notice_period_days = _parse_int("notice_period_days")
        contract.coverage_scope = _clean_str("coverage_scope")
        contract.start_date = _parse_date("start_date")
        contract.end_date = _parse_date("end_date")
        contract.renewal_date = _parse_date("renewal_date")
        contract.owner_id = _parse_int("owner_id")
        contract.support_email = _clean_str("support_email")
        contract.support_phone = _clean_str("support_phone")
        contract.support_url = _clean_str("support_url")
        contract.notes = _clean_str("notes")
        if not contract.status:
            contract.status = _default_contract_status(contract)
        has_document_uploads = any(file and file.filename for file in request.files.getlist(CONTRACT_DOCUMENT_FIELD))
        history_entry = None
        if not _same_snapshot(previous, contract) or has_document_uploads:
            history_entry = _add_history(contract, "updated", previous=previous, notes=_clean_str("history_notes") or "Manual update.")
        if has_document_uploads:
            _save_contract_documents(contract, history_entry=history_entry, notes=_clean_str("history_notes"))

        db.session.commit()
        return _json_or_redirect(True, f"Contract “{contract.name}” updated.", "success", "contracts.list_contracts")
    except Exception as exc:
        db.session.rollback()
        return _json_or_redirect(False, f"Failed to update contract: {exc}", "danger", "contracts.list_contracts")


@contracts_bp.route("/contracts/<int:contract_id>/details", methods=["GET"])
@login_required
def contract_details(contract_id):
    contract = Contract.query.get_or_404(contract_id)
    return jsonify(success=True, contract=contract.to_dict())


@contracts_bp.route("/contracts/<int:contract_id>/renew", methods=["POST"])
@login_required
def renew_contract(contract_id):
    contract = Contract.query.get_or_404(contract_id)
    require_module_write("contracts")
    try:
        previous = _contract_snapshot(contract)
        new_start_date = _parse_date("new_start_date")
        new_end_date = _parse_date("new_end_date")
        if not new_start_date or not new_end_date:
            return _json_or_redirect(False, "New start and end dates are required.", "warning", "contracts.list_contracts")
        if new_end_date < new_start_date:
            return _json_or_redirect(False, "New end date cannot be before the new start date.", "warning", "contracts.list_contracts")

        contract.start_date = new_start_date
        contract.end_date = new_end_date
        contract.renewal_date = _parse_date("new_renewal_date")
        contract.status = _clean_str("new_status") or "Active"
        value = _parse_decimal("new_value")
        if value is not None:
            contract.value = value
        currency = _clean_str("new_currency")
        if currency:
            contract.currency = currency
        notes = _clean_str("renewal_notes")
        if notes:
            existing_notes = contract.notes or ""
            contract.notes = f"{existing_notes}\n\nRenewal note: {notes}".strip()

        history_entry = _add_history(contract, "renewed", previous=previous, notes=notes or "Renewed for next period.")
        _save_contract_documents(
            contract,
            history_entry=history_entry,
            start_date=contract.start_date,
            end_date=contract.end_date,
            notes=notes,
        )
        db.session.commit()
        return _json_or_redirect(True, f"Contract “{contract.name}” renewed for the next period.", "success", "contracts.list_contracts")
    except Exception as exc:
        db.session.rollback()
        return _json_or_redirect(False, f"Failed to renew contract: {exc}", "danger", "contracts.list_contracts")


@contracts_bp.route("/contracts/<int:contract_id>/renew/defaults", methods=["GET"])
@login_required
def renewal_defaults(contract_id):
    contract = Contract.query.get_or_404(contract_id)
    next_start, next_end, next_renewal = _default_next_period(contract)
    return jsonify(
        success=True,
        defaults={
            "new_start_date": next_start.isoformat(),
            "new_end_date": next_end.isoformat(),
            "new_renewal_date": next_renewal.isoformat() if next_renewal else "",
            "new_status": "Active",
            "new_value": str(contract.value) if contract.value is not None else "",
            "new_currency": contract.currency or "",
        },
    )


@contracts_bp.route("/contracts/documents/<int:document_id>/download", methods=["GET"])
@login_required
def download_contract_document(document_id):
    document = ContractDocument.query.get_or_404(document_id)
    folder = _contract_upload_folder()
    path = os.path.join(folder, document.stored_filename)
    if not os.path.isfile(path):
        abort(404)
    return send_from_directory(
        folder,
        document.stored_filename,
        as_attachment=True,
        download_name=document.display_filename,
        mimetype=_document_mimetype(document.display_filename or document.stored_filename),
    )


@contracts_bp.route("/contracts/documents/<int:document_id>/open", methods=["GET"])
@login_required
def open_contract_document(document_id):
    document = ContractDocument.query.get_or_404(document_id)
    folder = _contract_upload_folder()
    path = os.path.join(folder, document.stored_filename)
    if not os.path.isfile(path):
        abort(404)
    ext = _document_extension(document.display_filename or document.stored_filename)
    return send_from_directory(
        folder,
        document.stored_filename,
        as_attachment=ext not in CONTRACT_DOCUMENT_INLINE_EXTENSIONS,
        download_name=document.display_filename,
        mimetype=_document_mimetype(document.display_filename or document.stored_filename),
    )


@contracts_bp.route("/contracts/documents/<int:document_id>/delete", methods=["POST"])
@login_required
def delete_contract_document(document_id):
    document = ContractDocument.query.get_or_404(document_id)
    require_module_write("contracts")
    try:
        display_filename = document.display_filename or document.stored_filename
        stored_filename = document.stored_filename
        folder = _contract_upload_folder()
        db.session.delete(document)
        if stored_filename:
            path = os.path.join(folder, stored_filename)
            if os.path.isfile(path):
                os.remove(path)
        db.session.commit()
        return _json_or_redirect(
            True,
            f"Document “{display_filename}” deleted.",
            "success",
            "contracts.list_contracts",
        )
    except Exception as exc:
        db.session.rollback()
        return _json_or_redirect(
            False,
            f"Failed to delete document: {exc}",
            "danger",
            "contracts.list_contracts",
        )


@contracts_bp.route("/contracts/<int:contract_id>/delete", methods=["POST"])
@login_required
def delete_contract(contract_id):
    contract = Contract.query.get_or_404(contract_id)
    require_module_write("contracts")
    try:
        name = contract.name
        db.session.delete(contract)
        db.session.commit()
        return _json_or_redirect(True, f"Contract “{name}” deleted.", "success", "contracts.list_contracts")
    except Exception as exc:
        db.session.rollback()
        return _json_or_redirect(False, f"Failed to delete contract: {exc}", "danger", "contracts.list_contracts")
