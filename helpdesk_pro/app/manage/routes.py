# -*- coding: utf-8 -*-
"""
Manage blueprint routes (access control, admin utilities).
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_babel import gettext as _

from app import db
from app.models import MenuPermission
from app.navigation import MENU_DEFINITIONS, AVAILABLE_ROLES, flatten_menu, default_allowed, definition_map


manage_bp = Blueprint("manage", __name__, url_prefix="/manage")


def _require_admin():
    if not current_user.is_authenticated or current_user.role != "admin":
        from flask import abort
        abort(403)


@manage_bp.route("/access", methods=["GET", "POST"])
@login_required
def access():
    _require_admin()

    flat_items = flatten_menu()
    definition_lookup = definition_map()

    if request.method == "POST":
        updated = False
        for item in flat_items:
            item_key = item["key"]
            definition = definition_lookup.get(item_key, {})
            for role in AVAILABLE_ROLES:
                field_name = f"perm_{item_key}_{role}"
                selected = field_name in request.form
                default = default_allowed(definition, type("obj", (object,), {"role": role})())
                perm = MenuPermission.query.filter_by(menu_key=item_key, role=role, user_id=None).first()
                if selected == default:
                    if perm:
                        db.session.delete(perm)
                        updated = True
                else:
                    if perm:
                        if perm.allowed != selected:
                            perm.allowed = selected
                            updated = True
                    else:
                        db.session.add(MenuPermission(menu_key=item_key, role=role, allowed=selected))
                        updated = True
        if updated:
            db.session.commit()
            flash(_("Access settings updated."), "success")
        else:
            flash(_("No changes were necessary."), "info")
        return redirect(url_for("manage.access"))

    # For GET, build display data (include defaults and overrides)
    display_items = []
    for item in flat_items:
        entry = {
            "key": item["key"],
            "label": item["label"],
            "has_children": item["has_children"],
            "roles": [],
        }
        for role in AVAILABLE_ROLES:
            definition = definition_lookup.get(item["key"], {})
            default = default_allowed(definition, type("obj", (object,), {"role": role})())
            perm = MenuPermission.query.filter_by(menu_key=item["key"], role=role, user_id=None).first()
            current = perm.allowed if perm is not None else default
            entry["roles"].append({
                "role": role,
                "current": current,
                "default": default,
            })
        display_items.append(entry)

    return render_template(
        "manage/access.html",
        menu_items=display_items,
        roles=AVAILABLE_ROLES,
    )
