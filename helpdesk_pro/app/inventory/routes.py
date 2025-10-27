# -*- coding: utf-8 -*-
"""
Inventory blueprint routes.
Provides software and hardware asset registries with CRUD endpoints and
DataTable-powered list views for Helpdesk Pro.
"""

from collections import Counter
from datetime import datetime

from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    flash,
)
from flask_login import login_required

from app import db
from app.models import SoftwareAsset, HardwareAsset, User

inventory_bp = Blueprint("inventory", __name__)

SOFTWARE_CATEGORIES = [
    "Operating System",
    "Office / Productivity",
    "Security",
    "Development",
    "Database",
    "Analytics",
    "Collaboration",
    "Cloud Service",
    "Other",
]
SOFTWARE_LICENSE_TYPES = [
    "Subscription",
    "Perpetual",
    "OEM",
    "Open Source",
    "Trial / Evaluation",
    "Site License",
]
SOFTWARE_ENVIRONMENTS = [
    "Production",
    "Staging",
    "QA",
    "Development",
    "Lab",
]
SOFTWARE_PLATFORMS = [
    "Windows",
    "macOS",
    "Linux",
    "Web",
    "Mobile",
    "Multi-platform",
]
SOFTWARE_STATUSES = [
    "Active",
    "Expiring Soon",
    "Expired",
    "Retired",
    "Planned",
]

HARDWARE_CATEGORIES = [
    "Laptop",
    "Desktop",
    "Server",
    "Network",
    "Peripheral",
    "Monitor",
    "TV",
    "Mobile Device",
    "Storage",
    "Printer",
    "Audio / Video",
    "Other",
]
HARDWARE_TYPES = [
    "Workstation",
    "Ultrabook",
    "Rack Server",
    "Tower Server",
    "Router",
    "Switch",
    "Firewall",
    "UPS",
    "IoT Device",
    "VOIP Phone",
    "Other",
]
HARDWARE_STATUSES = [
    "In Service",
    "In Stock",
    "Under Maintenance",
    "Retired",
    "Disposed",
]
HARDWARE_CONDITIONS = [
    "Excellent",
    "Good",
    "Needs Repair",
    "Damaged",
]


def _parse_date(field_name):
    value = request.form.get(field_name)
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_int(field_name):
    value = request.form.get(field_name)
    if not value:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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


@inventory_bp.route("/inventory/software")
@login_required
def software_list():
    assets = SoftwareAsset.query.order_by(SoftwareAsset.name.asc()).all()
    users = User.query.filter_by(active=True).order_by(User.username.asc()).all()
    status_summary = Counter(asset.status or "Unspecified" for asset in assets)
    expired_count = sum(
        1 for asset in assets if asset.expiration_date and asset.expiration_date <= datetime.utcnow().date()
    )
    return render_template(
        "inventory/software_list.html",
        assets=assets,
        users=users,
        status_summary=status_summary,
        expired_count=expired_count,
        categories=SOFTWARE_CATEGORIES,
        license_types=SOFTWARE_LICENSE_TYPES,
        environments=SOFTWARE_ENVIRONMENTS,
        platforms=SOFTWARE_PLATFORMS,
        statuses=SOFTWARE_STATUSES,
    )


@inventory_bp.route("/inventory/software/create", methods=["POST"])
@login_required
def create_software():
    try:
        name = _clean_str("name")
        if not name:
            return _json_or_redirect(False, "Name is required.", "warning", "inventory.software_list")

        asset = SoftwareAsset(
            name=name,
            category=_clean_str("category"),
            vendor=_clean_str("vendor"),
            version=_clean_str("version"),
            license_type=_clean_str("license_type"),
            license_key=_clean_str("license_key"),
            serial_number=_clean_str("serial_number"),
            custom_tag=_clean_str("custom_tag"),
            seats=_parse_int("seats"),
            platform=_clean_str("platform"),
            environment=_clean_str("environment"),
            status=_clean_str("status"),
            cost_center=_clean_str("cost_center"),
            purchase_date=_parse_date("purchase_date"),
            expiration_date=_parse_date("expiration_date"),
            renewal_date=_parse_date("renewal_date"),
            support_vendor=_clean_str("support_vendor"),
            support_email=_clean_str("support_email"),
            support_phone=_clean_str("support_phone"),
            contract_url=_clean_str("contract_url"),
            usage_scope=_clean_str("usage_scope"),
            deployment_notes=_clean_str("deployment_notes"),
        )

        assigned_to = _parse_int("assigned_to")
        if assigned_to:
            asset.assigned_to = assigned_to
        assigned_on = _parse_date("assigned_on")
        if assigned_on:
            asset.assigned_on = assigned_on
        elif assigned_to and not assigned_on:
            asset.assigned_on = datetime.utcnow().date()

        db.session.add(asset)
        db.session.commit()
        return _json_or_redirect(True, f"Software asset “{asset.name}” added.", "success", "inventory.software_list")
    except Exception as exc:
        db.session.rollback()
        return _json_or_redirect(False, f"Failed to add software asset: {exc}", "danger", "inventory.software_list")


@inventory_bp.route("/inventory/software/<int:asset_id>/update", methods=["POST"])
@login_required
def update_software(asset_id):
    asset = SoftwareAsset.query.get_or_404(asset_id)
    try:
        asset.name = _clean_str("name") or asset.name
        asset.category = _clean_str("category")
        asset.vendor = _clean_str("vendor")
        asset.version = _clean_str("version")
        asset.license_type = _clean_str("license_type")
        asset.license_key = _clean_str("license_key")
        asset.serial_number = _clean_str("serial_number")
        asset.custom_tag = _clean_str("custom_tag")
        asset.seats = _parse_int("seats")
        asset.platform = _clean_str("platform")
        asset.environment = _clean_str("environment")
        asset.status = _clean_str("status")
        asset.cost_center = _clean_str("cost_center")
        asset.purchase_date = _parse_date("purchase_date")
        asset.expiration_date = _parse_date("expiration_date")
        asset.renewal_date = _parse_date("renewal_date")
        asset.support_vendor = _clean_str("support_vendor")
        asset.support_email = _clean_str("support_email")
        asset.support_phone = _clean_str("support_phone")
        asset.contract_url = _clean_str("contract_url")
        asset.usage_scope = _clean_str("usage_scope")
        asset.deployment_notes = _clean_str("deployment_notes")

        assigned_to = _parse_int("assigned_to")
        asset.assigned_to = assigned_to
        assigned_on = _parse_date("assigned_on")
        if assigned_on:
            asset.assigned_on = assigned_on
        else:
            asset.assigned_on = None if not assigned_to else datetime.utcnow().date()

        db.session.commit()
        return _json_or_redirect(True, f"Software asset “{asset.name}” updated.", "success", "inventory.software_list")
    except Exception as exc:
        db.session.rollback()
        return _json_or_redirect(False, f"Failed to update software asset: {exc}", "danger", "inventory.software_list")


@inventory_bp.route("/inventory/software/<int:asset_id>/details", methods=["GET"])
@login_required
def software_details(asset_id):
    asset = SoftwareAsset.query.get_or_404(asset_id)
    return jsonify(success=True, asset=asset.to_dict())


@inventory_bp.route("/inventory/software/<int:asset_id>/delete", methods=["POST"])
@login_required
def delete_software(asset_id):
    asset = SoftwareAsset.query.get_or_404(asset_id)
    try:
        name = asset.name
        db.session.delete(asset)
        db.session.commit()
        return _json_or_redirect(True, f"Software asset “{name}” deleted.", "success", "inventory.software_list")
    except Exception as exc:
        db.session.rollback()
        return _json_or_redirect(False, f"Failed to delete software asset: {exc}", "danger", "inventory.software_list")


@inventory_bp.route("/inventory/hardware")
@login_required
def hardware_list():
    assets = HardwareAsset.query.order_by(HardwareAsset.asset_tag.asc()).all()
    users = User.query.filter_by(active=True).order_by(User.username.asc()).all()
    status_summary = Counter(asset.status or "Unspecified" for asset in assets)
    return render_template(
        "inventory/hardware_list.html",
        assets=assets,
        users=users,
        status_summary=status_summary,
        categories=HARDWARE_CATEGORIES,
        hardware_types=HARDWARE_TYPES,
        statuses=HARDWARE_STATUSES,
        conditions=HARDWARE_CONDITIONS,
    )


@inventory_bp.route("/inventory/hardware/create", methods=["POST"])
@login_required
def create_hardware():
    try:
        asset_tag = _clean_str("asset_tag")
        if not asset_tag:
            return _json_or_redirect(False, "Asset tag is required.", "warning", "inventory.hardware_list")

        asset = HardwareAsset(
            asset_tag=asset_tag,
            serial_number=_clean_str("serial_number"),
            custom_tag=_clean_str("custom_tag"),
            category=_clean_str("category"),
            type=_clean_str("type"),
            manufacturer=_clean_str("manufacturer"),
            model=_clean_str("model"),
            cpu=_clean_str("cpu"),
            ram_gb=_clean_str("ram_gb"),
            storage=_clean_str("storage"),
            gpu=_clean_str("gpu"),
            operating_system=_clean_str("operating_system"),
            ip_address=_clean_str("ip_address"),
            mac_address=_clean_str("mac_address"),
            hostname=_clean_str("hostname"),
            location=_clean_str("location"),
            rack=_clean_str("rack"),
            status=_clean_str("status"),
            condition=_clean_str("condition"),
            purchase_date=_parse_date("purchase_date"),
            warranty_end=_parse_date("warranty_end"),
            support_vendor=_clean_str("support_vendor"),
            support_contract=_clean_str("support_contract"),
            accessories=_clean_str("accessories"),
            power_supply=_clean_str("power_supply"),
            bios_version=_clean_str("bios_version"),
            firmware_version=_clean_str("firmware_version"),
            notes=_clean_str("notes"),
        )

        assigned_to = _parse_int("assigned_to")
        if assigned_to:
            asset.assigned_to = assigned_to
        assigned_on = _parse_date("assigned_on")
        if assigned_on:
            asset.assigned_on = assigned_on
        elif assigned_to and not assigned_on:
            asset.assigned_on = datetime.utcnow().date()

        db.session.add(asset)
        db.session.commit()
        return _json_or_redirect(True, f"Hardware asset “{asset.asset_tag}” added.", "success", "inventory.hardware_list")
    except Exception as exc:
        db.session.rollback()
        return _json_or_redirect(False, f"Failed to add hardware asset: {exc}", "danger", "inventory.hardware_list")


@inventory_bp.route("/inventory/hardware/<int:asset_id>/update", methods=["POST"])
@login_required
def update_hardware(asset_id):
    asset = HardwareAsset.query.get_or_404(asset_id)
    try:
        asset.asset_tag = _clean_str("asset_tag") or asset.asset_tag
        asset.serial_number = _clean_str("serial_number")
        asset.custom_tag = _clean_str("custom_tag")
        asset.category = _clean_str("category")
        asset.type = _clean_str("type")
        asset.manufacturer = _clean_str("manufacturer")
        asset.model = _clean_str("model")
        asset.cpu = _clean_str("cpu")
        asset.ram_gb = _clean_str("ram_gb")
        asset.storage = _clean_str("storage")
        asset.gpu = _clean_str("gpu")
        asset.operating_system = _clean_str("operating_system")
        asset.ip_address = _clean_str("ip_address")
        asset.mac_address = _clean_str("mac_address")
        asset.hostname = _clean_str("hostname")
        asset.location = _clean_str("location")
        asset.rack = _clean_str("rack")
        asset.status = _clean_str("status")
        asset.condition = _clean_str("condition")
        asset.purchase_date = _parse_date("purchase_date")
        asset.warranty_end = _parse_date("warranty_end")
        asset.support_vendor = _clean_str("support_vendor")
        asset.support_contract = _clean_str("support_contract")
        asset.accessories = _clean_str("accessories")
        asset.power_supply = _clean_str("power_supply")
        asset.bios_version = _clean_str("bios_version")
        asset.firmware_version = _clean_str("firmware_version")
        asset.notes = _clean_str("notes")

        assigned_to = _parse_int("assigned_to")
        asset.assigned_to = assigned_to
        assigned_on = _parse_date("assigned_on")
        if assigned_on:
            asset.assigned_on = assigned_on
        else:
            asset.assigned_on = None if not assigned_to else datetime.utcnow().date()

        db.session.commit()
        return _json_or_redirect(True, f"Hardware asset “{asset.asset_tag}” updated.", "success", "inventory.hardware_list")
    except Exception as exc:
        db.session.rollback()
        return _json_or_redirect(False, f"Failed to update hardware asset: {exc}", "danger", "inventory.hardware_list")


@inventory_bp.route("/inventory/hardware/<int:asset_id>/details", methods=["GET"])
@login_required
def hardware_details(asset_id):
    asset = HardwareAsset.query.get_or_404(asset_id)
    return jsonify(success=True, asset=asset.to_dict())


@inventory_bp.route("/inventory/hardware/<int:asset_id>/delete", methods=["POST"])
@login_required
def delete_hardware(asset_id):
    asset = HardwareAsset.query.get_or_404(asset_id)
    try:
        asset_tag = asset.asset_tag
        db.session.delete(asset)
        db.session.commit()
        return _json_or_redirect(True, f"Hardware asset “{asset_tag}” deleted.", "success", "inventory.hardware_list")
    except Exception as exc:
        db.session.rollback()
        return _json_or_redirect(False, f"Failed to delete hardware asset: {exc}", "danger", "inventory.hardware_list")
