# -*- coding: utf-8 -*-
"""
Navigation utilities for building dynamic menus based on role/user permissions.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from flask import url_for, g
from flask_login import current_user
from flask_babel import gettext as _

from app.models import MenuPermission


AVAILABLE_ROLES = ["admin", "manager", "technician", "user"]


MENU_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "key": "dashboard",
        "label": _("Dashboard"),
        "icon": "fa fa-chart-line",
        "endpoint": "dashboard.index",
        "roles": ["admin", "manager"],
        "order": 10,
    },
    {
        "key": "manage",
        "label": _("Manage"),
        "icon": "fa fa-sliders",
        "roles": ["admin"],
        "order": 20,
        "children": [
            {
                "key": "manage_users",
                "label": _("Users"),
                "icon": "fa fa-users text-primary",
                "endpoint": "users.list_users",
                "roles": ["admin"],
            },
            {
                "key": "manage_access",
                "label": _("Access"),
                "icon": "fa fa-key text-warning",
                "endpoint": "manage.access",
                "roles": ["admin"],
            },
            {
                "key": "manage_auth",
                "label": _("Authentication"),
                "icon": "fa fa-user-shield text-info",
                "endpoint": "manage.auth_settings",
                "roles": ["admin"],
            },
            {
                "key": "manage_assistant",
                "label": _("AI Assistant"),
                "icon": "fa fa-robot text-success",
                "endpoint": "manage.assistant_settings",
                "roles": ["admin"],
            },
            {
                "key": "manage_configuration",
                "label": _("Configuration"),
                "icon": "fa fa-gears text-info",
                "endpoint": "manage.configuration",
                "roles": ["admin"],
            },
            {
                "key": "manage_api",
                "label": _("API Keys"),
                "icon": "fa fa-key text-danger",
                "endpoint": "manage.api_keys",
                "roles": ["admin"],
            },
            {
                "key": "manage_api_docs",
                "label": _("API Docs"),
                "icon": "fa fa-book-open text-secondary",
                "endpoint": "manage.api_docs",
                "roles": ["admin"],
            },
            {
                "key": "manage_email_ingest",
                "label": _("Email to Ticket"),
                "icon": "fa fa-envelope-open-text text-success",
                "endpoint": "manage.email_ingest",
                "roles": ["admin"],
            },
        ],
    },
    {
        "key": "tickets",
        "label": _("Tickets"),
        "icon": "fa fa-ticket",
        "endpoint": "tickets.list_tickets",
        "roles": ["admin", "manager", "technician", "user"],
        "order": 30,
    },
    {
        "key": "knowledge",
        "label": _("Knowledge Base"),
        "icon": "fa fa-book",
        "roles": ["admin", "manager", "technician", "user"],
        "order": 40,
        "endpoint": "knowledge.list_articles",
    },
    {
        "key": "collaboration",
        "label": _("Collaboration"),
        "icon": "fa fa-comments",
        "roles": ["admin", "manager", "technician", "user"],
        "order": 50,
        "endpoint": "collab.chat_home",
    },
    {
        "key": "it_works",
        "label": _("IT Works"),
        "icon": "fa fa-screwdriver-wrench",
        "roles": ["admin", "manager", "technician"],
        "order": 60,
        "children": [
            {
                "key": "inventory_software",
                "label": _("Software"),
                "icon": "fa fa-code-branch text-primary",
                "roles": ["admin"],
                "endpoint": "inventory.software_list",
            },
            {
                "key": "inventory_hardware",
                "label": _("Hardware"),
                "icon": "fa fa-microchip text-secondary",
                "roles": ["admin"],
                "endpoint": "inventory.hardware_list",
            },
            {
                "key": "contracts",
                "label": _("Contracts"),
                "icon": "fa fa-file-contract",
                "roles": ["admin", "manager"],
                "endpoint": "contracts.list_contracts",
            },
            {
                "key": "address_book",
                "label": _("Address Book"),
                "icon": "fa fa-address-book text-success",
                "roles": ["admin", "manager", "technician"],
                "endpoint": "address_book.directory",
            },
            {
                "key": "networks_maps",
                "label": _("Network Maps"),
                "icon": "fa fa-sitemap text-info",
                "roles": ["admin"],
                "endpoint": "networks.network_maps",
            },
            {
                "key": "networks_tools",
                "label": _("Network Tools"),
                "icon": "fa fa-toolbox text-warning",
                "roles": ["admin"],
                "endpoint": "networks.network_tools",
            },
            {
                "key": "backup_monitor",
                "label": _("Backup Monitor"),
                "icon": "fa fa-database text-primary",
                "roles": ["admin", "manager", "technician"],
                "endpoint": "backup.monitor",
            },
            {
                "key": "lto_barcode_generator",
                "label": _("LTO Barcode Generator"),
                "icon": "fa fa-barcode text-info",
                "roles": ["admin", "manager", "technician"],
                "endpoint": "backup.lto_barcode_generator",
            },
            {
                "key": "password_workbench",
                "label": _("Password & PIN Studio"),
                "icon": "fa fa-key text-danger",
                "roles": ["admin", "manager", "technician"],
                "endpoint": "tools.password_generator",
            },
        ],
    },
    {
        "key": "assistant_widget",
        "label": _("AI Assistant Widget"),
        "icon": "fa fa-robot",
        "roles": ["admin", "manager", "technician", "user"],
        "order": 200,
        "show_in_nav": False,
        "auth_required": True,
    },
    {
        "key": "email2ticket",
        "label": _("Email to Ticket Worker"),
        "icon": "fa fa-envelope-circle-check",
        "roles": ["admin"],
        "order": 210,
        "show_in_nav": False,
        "auth_required": True,
    },
]


def default_allowed(item: Dict[str, Any], user) -> bool:
    roles = item.get("roles")
    if not roles:
        return True
    if not user or not getattr(user, "role", None):
        return False
    return user.role in roles


def resolve_menu_item(item: Dict[str, Any], user) -> Optional[Dict[str, Any]]:
    if item.get("show_in_nav") is False:
        return None

    allowed = default_allowed(item, user)

    if user and user.is_authenticated:
        user_perm = MenuPermission.query.filter_by(menu_key=item["key"], user_id=user.id).first()
        if user_perm:
            allowed = user_perm.allowed
        else:
            role_perm = MenuPermission.query.filter_by(menu_key=item["key"], user_id=None, role=user.role).first()
            if role_perm:
                allowed = role_perm.allowed
    else:
        if item.get("auth_required", True):
            allowed = False

    if not allowed:
        return None

    children = item.get("children")
    if children:
        resolved_children = []
        for child in children:
            resolved = resolve_menu_item(child, user)
            if resolved:
                resolved_children.append(resolved)
        if not resolved_children:
            return None
        return {
            "type": "dropdown",
            "key": item["key"],
            "label": item["label"],
            "icon": item.get("icon"),
            "children": resolved_children,
            "order": item.get("order", 0),
        }

    endpoint_kwargs = item.get("endpoint_kwargs", {})
    if "lang" not in endpoint_kwargs and hasattr(g, "locale"):
        endpoint_kwargs = {**endpoint_kwargs, "lang": g.locale}
    return {
        "type": "link",
        "key": item["key"],
        "label": item["label"],
        "icon": item.get("icon"),
        "url": url_for(item["endpoint"], **endpoint_kwargs),
        "order": item.get("order", 0),
    }


def get_navigation_for_user(user) -> List[Dict[str, Any]]:
    navigation = []
    for item in sorted(MENU_DEFINITIONS, key=lambda x: x.get("order", 0)):
        resolved = resolve_menu_item(item, user)
        if resolved:
            navigation.append(resolved)
    return navigation


def flatten_menu(definitions: Optional[List[Dict[str, Any]]] = None, include_groups: bool = True) -> List[Dict[str, Any]]:
    definitions = definitions or MENU_DEFINITIONS
    items: List[Dict[str, Any]] = []
    for item in definitions:
        entry = {
            "key": item["key"],
            "label": item["label"],
            "roles": item.get("roles"),
            "has_children": bool(item.get("children")),
        }
        if include_groups or not entry["has_children"]:
            items.append(entry)
        if item.get("children"):
            items.extend(flatten_menu(item["children"], include_groups=include_groups))
    return items


def definition_map(definitions: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Dict[str, Any]]:
    definitions = definitions or MENU_DEFINITIONS
    mapping: Dict[str, Dict[str, Any]] = {}
    for item in definitions:
        mapping[item["key"]] = item
        if item.get("children"):
            mapping.update(definition_map(item["children"]))
    return mapping


def is_feature_allowed(key: str, user) -> bool:
    definitions = definition_map()
    item = definitions.get(key)
    if not item:
        return False

    allowed = default_allowed(item, user)
    if user and getattr(user, "is_authenticated", False):
        user_perm = MenuPermission.query.filter_by(menu_key=key, user_id=user.id).first()
        if user_perm:
            return user_perm.allowed
        role_perm = MenuPermission.query.filter_by(menu_key=key, user_id=None, role=user.role).first()
        if role_perm:
            return role_perm.allowed
    else:
        if item.get("auth_required", True):
            return False
    return allowed
