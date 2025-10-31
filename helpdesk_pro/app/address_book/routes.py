# -*- coding: utf-8 -*-
"""
Address book blueprint routes.
Provides contact directory management with CRUD operations.
"""

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
from sqlalchemy import func

from app import db
from app.models import AddressBookEntry

address_book_bp = Blueprint("address_book", __name__)

ADDRESS_CATEGORIES = ["Vendor", "Partner", "Customer", "Internal", "Other"]
CHUNK_SIZE = 500


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
    query = AddressBookEntry.query.order_by(AddressBookEntry.name.asc())
    entries = query.limit(CHUNK_SIZE).all()

    total_entries = db.session.query(func.count(AddressBookEntry.id)).scalar() or 0

    category_rows = (
        db.session.query(AddressBookEntry.category, func.count(AddressBookEntry.id))
        .group_by(AddressBookEntry.category)
        .all()
    )
    category_counts = {}
    unspecified_total = 0
    for category, count in category_rows:
        if category:
            category_counts[category] = count
        else:
            unspecified_total += count
    if unspecified_total:
        category_counts["Unspecified"] = unspecified_total

    has_more = total_entries > len(entries)
    next_offset = len(entries)

    return render_template(
        "address_book/address_book.html",
        entries=entries,
        categories=ADDRESS_CATEGORIES,
        category_counts=category_counts,
        total_entries=total_entries,
        has_more=has_more,
        next_offset=next_offset,
        chunk_size=CHUNK_SIZE,
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


@address_book_bp.route("/address-book/api/list", methods=["GET"])
@login_required
def list_entries_api():
    try:
        offset = int(request.args.get("offset", 0))
        if offset < 0:
            offset = 0
    except (TypeError, ValueError):
        offset = 0

    try:
        limit = int(request.args.get("limit", CHUNK_SIZE))
        if limit <= 0 or limit > CHUNK_SIZE:
            limit = CHUNK_SIZE
    except (TypeError, ValueError):
        limit = CHUNK_SIZE

    query = AddressBookEntry.query.order_by(AddressBookEntry.name.asc())
    total = db.session.query(func.count(AddressBookEntry.id)).scalar() or 0
    entries = query.offset(offset).limit(limit).all()

    payload = []
    for entry in entries:
        data = entry.to_dict()
        data.update(
            {
                "id": entry.id,
                "update_url": url_for("address_book.update_entry", entry_id=entry.id),
                "delete_url": url_for("address_book.delete_entry", entry_id=entry.id),
                "details_url": url_for("address_book.entry_details", entry_id=entry.id),
            }
        )
        payload.append(data)

    next_offset = offset + len(entries)
    has_more = next_offset < total

    return jsonify(
        success=True,
        entries=payload,
        next_offset=next_offset,
        has_more=has_more,
        total=total,
    )
