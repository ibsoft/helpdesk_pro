# -*- coding: utf-8 -*-
"""
Contracts blueprint routes.
Provides lifecycle tracking for software, hardware, and services agreements.
"""

from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    flash,
)
from flask_login import login_required, current_user

from app import db
from app.models import Contract, User
from app.permissions import get_module_access, require_module_write

contracts_bp = Blueprint("contracts", __name__)

CONTRACT_TYPES = ["Software", "Hardware", "Services"]
CONTRACT_STATUSES = ["Active", "Pending", "Expiring Soon", "Expired", "Terminated", "On Hold"]


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


@contracts_bp.route("/contracts")
@login_required
def list_contracts():
    today = datetime.utcnow().date()
    contracts = Contract.query.order_by(Contract.end_date.asc().nullslast(), Contract.name.asc()).all()
    users = User.query.filter_by(active=True).order_by(User.username.asc()).all()

    status_summary = Counter(contract.status or "Unspecified" for contract in contracts)
    expiring_threshold = today + timedelta(days=60)
    expiring_soon = sum(
        1
        for contract in contracts
        if contract.end_date and today <= contract.end_date <= expiring_threshold
    )
    expired_count = sum(
        1 for contract in contracts if contract.end_date and contract.end_date < today
    )

    module_access = get_module_access(current_user, "contracts")
    return render_template(
        "contracts/contract_list.html",
        contracts=contracts,
        users=users,
        contract_types=CONTRACT_TYPES,
        contract_statuses=CONTRACT_STATUSES,
        status_summary=status_summary,
        expiring_soon=expiring_soon,
        expired_count=expired_count,
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

        db.session.add(contract)
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
