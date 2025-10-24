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
        "label": "Dashboard",
        "icon": "fa fa-chart-line",
        "endpoint": "dashboard.index",
        "roles": ["admin", "manager"],
        "order": 10,
    },
    {
        "key": "tickets",
        "label": "Tickets",
        "icon": "fa fa-ticket",
        "endpoint": "tickets.list_tickets",
        "roles": ["admin", "manager", "technician", "user"],
        "order": 20,
    },
    {
        "key": "inventory",
        "label": "Inventory",
        "icon": "fa fa-boxes-stacked",
        "roles": ["admin"],
        "order": 30,
        "children": [
            {
                "key": "inventory_software",
                "label": "Software",
                "icon": "fa fa-code-branch text-primary",
                "endpoint": "inventory.software_list",
                "roles": ["admin"],
            },
            {
                "key": "inventory_hardware",
                "label": "Hardware",
                "icon": "fa fa-microchip text-secondary",
                "endpoint": "inventory.hardware_list",
                "roles": ["admin"],
            },
        ],
    },
    {
        "key": "networks",
        "label": "Networks",
        "icon": "fa fa-network-wired",
        "roles": ["admin"],
        "order": 40,
        "children": [
            {
                "key": "networks_maps",
                "label": "Network Maps",
                "icon": "fa fa-sitemap text-info",
                "endpoint": "networks.network_maps",
                "roles": ["admin"],
            },
            {
                "key": "networks_tools",
                "label": "Network Tools",
                "icon": "fa fa-toolbox text-warning",
                "endpoint": "networks.network_tools",
                "roles": ["admin"],
            },
        ],
    },
    {
        "key": "manage",
        "label": "Manage",
        "icon": "fa fa-sliders",
        "roles": ["admin"],
        "order": 50,
        "children": [
            {
                "key": "manage_users",
                "label": "Users",
                "icon": "fa fa-users",
                "endpoint": "users.list_users",
                "roles": ["admin"],
            },
            {
                "key": "manage_access",
                "label": "Access",
                "icon": "fa fa-key",
                "endpoint": "manage.access",
                "roles": ["admin"],
            },
        ],
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
