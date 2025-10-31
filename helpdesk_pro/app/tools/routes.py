# -*- coding: utf-8 -*-
"""
Utility tools (password/passphrase/PIN generators).
"""

from flask import Blueprint, render_template
from flask_login import login_required

tools_bp = Blueprint("tools", __name__, url_prefix="/tools")


@tools_bp.route("/passwords", methods=["GET"])
@login_required
def password_generator():
    return render_template("tools/password_generator.html")


__all__ = [
    "tools_bp",
]
