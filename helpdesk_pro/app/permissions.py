# -*- coding: utf-8 -*-
"""
Helpers for module-level access control.
"""

from functools import lru_cache
from typing import Optional

from flask_login import current_user

from app.models import ModulePermission

MODULE_ACCESS_DEFINITIONS = {
    "software": {"label": "Software Inventory"},
    "hardware": {"label": "Hardware Inventory"},
    "contracts": {"label": "Contracts"},
    "networks": {"label": "Network Maps & Tools"},
    "backup": {"label": "Backup Monitor"},
}

MODULE_ACCESS_LEVELS = ("read", "write")


@lru_cache(maxsize=128)
def _role_access_level(role: str, module_key: str) -> str:
    role = (role or "").strip().lower()
    module_key = module_key.strip().lower()
    perm = ModulePermission.query.filter_by(module_key=module_key, role=role).first()
    if perm and perm.access_level in MODULE_ACCESS_LEVELS:
        return perm.access_level
    return "write"


def clear_access_cache():
    _role_access_level.cache_clear()


def get_module_access(user, module_key: str) -> str:
    if not user or not getattr(user, "is_authenticated", False):
        return "read"
    if (user.role or "").strip().lower() == "admin":
        return "write"
    return _role_access_level(user.role, module_key)


def can_write_module(user, module_key: str) -> bool:
    return get_module_access(user, module_key) == "write"


def require_module_write(module_key: str):
    if not can_write_module(current_user, module_key):
        from flask import abort
        abort(403)
