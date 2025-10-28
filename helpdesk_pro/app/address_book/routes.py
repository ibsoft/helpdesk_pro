# -*- coding: utf-8 -*-
"""
Address book blueprint routes.
Provides contact directory management with CRUD operations.
"""

from collections import Counter

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
from app.models import AddressBookEntry

address_book_bp = Blueprint("address_book", __name__)

ADDRESS_CATEGORIES = ["Vendor", "Partner", "Customer", "Internal", "Other"]


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


@address_book_bp.route("/address-book")
@login_required
def directory():
    entries = AddressBookEntry.query.order_by(AddressBookEntry.name.asc()).all()
    category_counts = Counter(entry.category or "Unspecified" for entry in entries)
    return render_template(
        "address_book/address_book.html",
        entries=entries,
        categories=ADDRESS_CATEGORIES,
        category_counts=category_counts,
    )


@address_book_bp.route("/address-book/create", methods=["POST"])
@login_required
def create_entry():
    try:
        name = _clean_str("name")
        if not name:
            return _json_or_redirect(False, "Name is required.", "warning", "address_book.directory")

        entry = AddressBookEntry(
            name=name,
            category=_clean_str("category"),
            company=_clean_str("company"),
            job_title=_clean_str("job_title"),
            department=_clean_str("department"),
            email=_clean_str("email"),
            phone=_clean_str("phone"),
            mobile=_clean_str("mobile"),
            website=_clean_str("website"),
            address_line=_clean_str("address_line"),
            city=_clean_str("city"),
            state=_clean_str("state"),
            postal_code=_clean_str("postal_code"),
            country=_clean_str("country"),
            tags=_clean_str("tags"),
            notes=_clean_str("notes"),
        )

        db.session.add(entry)
        db.session.commit()
        return _json_or_redirect(True, f"Contact “{entry.name}” added.", "success", "address_book.directory")
    except Exception as exc:
        db.session.rollback()
        return _json_or_redirect(False, f"Failed to add contact: {exc}", "danger", "address_book.directory")


@address_book_bp.route("/address-book/<int:entry_id>/update", methods=["POST"])
@login_required
def update_entry(entry_id):
    entry = AddressBookEntry.query.get_or_404(entry_id)
    try:
        name = _clean_str("name")
        if name:
            entry.name = name
        entry.category = _clean_str("category")
        entry.company = _clean_str("company")
        entry.job_title = _clean_str("job_title")
        entry.department = _clean_str("department")
        entry.email = _clean_str("email")
        entry.phone = _clean_str("phone")
        entry.mobile = _clean_str("mobile")
        entry.website = _clean_str("website")
        entry.address_line = _clean_str("address_line")
        entry.city = _clean_str("city")
        entry.state = _clean_str("state")
        entry.postal_code = _clean_str("postal_code")
        entry.country = _clean_str("country")
        entry.tags = _clean_str("tags")
        entry.notes = _clean_str("notes")

        db.session.commit()
        return _json_or_redirect(True, f"Contact “{entry.name}” updated.", "success", "address_book.directory")
    except Exception as exc:
        db.session.rollback()
        return _json_or_redirect(False, f"Failed to update contact: {exc}", "danger", "address_book.directory")


@address_book_bp.route("/address-book/<int:entry_id>/details", methods=["GET"])
@login_required
def entry_details(entry_id):
    entry = AddressBookEntry.query.get_or_404(entry_id)
    return jsonify(success=True, entry=entry.to_dict())


@address_book_bp.route("/address-book/<int:entry_id>/delete", methods=["POST"])
@login_required
def delete_entry(entry_id):
    entry = AddressBookEntry.query.get_or_404(entry_id)
    try:
        name = entry.name
        db.session.delete(entry)
        db.session.commit()
        return _json_or_redirect(True, f"Contact “{name}” deleted.", "success", "address_book.directory")
    except Exception as exc:
        db.session.rollback()
        return _json_or_redirect(False, f"Failed to delete contact: {exc}", "danger", "address_book.directory")
