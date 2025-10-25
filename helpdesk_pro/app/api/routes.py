# -*- coding: utf-8 -*-
"""
Helpdesk Pro public REST API (v1).
Authentication is API-key based. Keys are managed through Manage → API Keys.
"""

from datetime import datetime, date
from typing import Optional, Iterable

from flask import Blueprint, jsonify, request, g
from sqlalchemy import or_

from app import db, csrf
from app.models import (
    ApiClient,
    Ticket,
    KnowledgeArticle,
    KnowledgeAttachment,
    SoftwareAsset,
    HardwareAsset,
    User,
)

api_bp = Blueprint("api", __name__)
csrf.exempt(api_bp)


# ───────── Helpers ───────── #
def _error(message: str, status: int = 400):
    return jsonify({"error": message}), status


def _extract_api_key() -> Optional[str]:
    header = request.headers.get("X-API-Key") or ""
    if not header and "Authorization" in request.headers:
        auth_header = request.headers.get("Authorization") or ""
        if auth_header.lower().startswith("bearer "):
            header = auth_header[7:].strip()
    return header.strip() or None


def _resolve_user(ref, *, allow_default: bool = True) -> Optional[User]:
    """
    Resolve a user from either id or username.
    """
    if ref is None or ref == "":
        return g.api_client.default_user if allow_default else None

    candidate = None
    if isinstance(ref, int):
        candidate = User.query.get(ref)
    else:
        text = str(ref).strip()
        if text.isdigit():
            candidate = User.query.get(int(text))
        else:
            candidate = User.query.filter(User.username.ilike(text)).first()
    if candidate:
        return candidate
    return g.api_client.default_user if allow_default else None


def _parse_date(value) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def _ticket_to_dict(ticket: Ticket) -> dict:
    return {
        "id": ticket.id,
        "subject": ticket.subject,
        "description": ticket.description,
        "priority": ticket.priority,
        "status": ticket.status,
        "department": ticket.department,
        "created_by": ticket.created_by,
        "assigned_to": ticket.assigned_to,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        "updated_at": ticket.updated_at.isoformat() if ticket.updated_at else None,
        "closed_at": ticket.closed_at.isoformat() if ticket.closed_at else None,
        "assignee": ticket.assignee.username if ticket.assignee else None,
    }


def _knowledge_to_dict(article: KnowledgeArticle) -> dict:
    return {
        "id": article.id,
        "title": article.title,
        "summary": article.summary,
        "content": article.content,
        "tags": article.tags,
        "category": article.category,
        "is_published": article.is_published,
        "created_by": article.created_by,
        "updated_by": article.updated_by,
        "created_at": article.created_at.isoformat() if article.created_at else None,
        "updated_at": article.updated_at.isoformat() if article.updated_at else None,
        "attachments": [
            {
                "id": att.id,
                "filename": att.original_filename,
                "uploaded_at": att.uploaded_at.isoformat() if att.uploaded_at else None,
                "size": att.file_size,
            }
            for att in article.attachments
        ],
    }


def _software_to_dict(asset: SoftwareAsset) -> dict:
    data = asset.to_dict()
    data["created_at"] = asset.created_at.isoformat() if asset.created_at else None
    data["updated_at"] = asset.updated_at.isoformat() if asset.updated_at else None
    return data


def _hardware_to_dict(asset: HardwareAsset) -> dict:
    data = asset.to_dict()
    data["created_at"] = asset.created_at.isoformat() if asset.created_at else None
    data["updated_at"] = asset.updated_at.isoformat() if asset.updated_at else None
    return data


def _build_openapi_spec() -> dict:
    base_url = request.host_url.rstrip("/")
    root = f"{base_url}/api/v1"

    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Helpdesk Pro API",
            "version": "1.0.0",
            "description": (
                "Programmatic access to Helpdesk Pro tickets, knowledge base, and inventory. "
                "All requests must include a valid API key using the `X-API-Key` header (or `Authorization: Bearer`)."
            ),
        },
        "servers": [{"url": root}],
        "security": [{"ApiKeyAuth": []}],
        "paths": {
            "/status": {
                "get": {
                    "summary": "API status",
                    "tags": ["Meta"],
                    "responses": {
                        "200": {
                            "description": "Service information",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "status": {"type": "string"},
                                            "timestamp": {"type": "string", "format": "date-time"},
                                            "client": {"$ref": "#/components/schemas/ApiClient"},
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/tickets": {
                "get": {
                    "summary": "List tickets",
                    "tags": ["Tickets"],
                    "parameters": [
                        {"name": "status", "in": "query", "schema": {"type": "string"}},
                        {"name": "department", "in": "query", "schema": {"type": "string"}},
                        {"name": "assigned_to", "in": "query", "schema": {"type": "string"}},
                    ],
                    "responses": {
                        "200": {
                            "description": "Ticket listing",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "tickets": {
                                                "type": "array",
                                                "items": {"$ref": "#/components/schemas/Ticket"},
                                            }
                                        },
                                    }
                                }
                            },
                        }
                    },
                },
                "post": {
                    "summary": "Create ticket",
                    "tags": ["Tickets"],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["subject", "description"],
                                    "properties": {
                                        "subject": {"type": "string"},
                                        "description": {"type": "string"},
                                        "priority": {"type": "string"},
                                        "status": {"type": "string"},
                                        "department": {"type": "string"},
                                        "created_by": {"type": "string"},
                                        "assigned_to": {"type": "string"},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "201": {
                            "description": "Ticket created",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/TicketResponse"}}},
                        }
                    },
                },
            },
            "/tickets/{ticket_id}": {
                "parameters": [
                    {
                        "name": "ticket_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "get": {
                    "summary": "Retrieve ticket",
                    "tags": ["Tickets"],
                    "responses": {
                        "200": {
                            "description": "Ticket",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/TicketResponse"}}},
                        },
                        "404": {"description": "Not found"},
                    },
                },
                "patch": {
                    "summary": "Update ticket",
                    "tags": ["Tickets"],
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "subject": {"type": "string"},
                                        "description": {"type": "string"},
                                        "priority": {"type": "string"},
                                        "status": {"type": "string"},
                                        "department": {"type": "string"},
                                        "assigned_to": {"type": "string"},
                                        "closed_at": {"type": "string", "format": "date-time"},
                                    },
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Ticket",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/TicketResponse"}}},
                        }
                    },
                },
                "delete": {
                    "summary": "Delete ticket",
                    "tags": ["Tickets"],
                    "responses": {"200": {"description": "Deleted"}, "404": {"description": "Not found"}},
                },
            },
            "/knowledge": {
                "get": {
                    "summary": "Search knowledge base",
                    "tags": ["Knowledge"],
                    "parameters": [
                        {
                            "name": "q",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Results",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "results": {
                                                "type": "array",
                                                "items": {"$ref": "#/components/schemas/KnowledgeArticle"},
                                            }
                                        },
                                    }
                                }
                            },
                        },
                        "400": {"description": "Missing query"},
                    },
                },
                "post": {
                    "summary": "Create knowledge article",
                    "tags": ["Knowledge"],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["title", "content"],
                                    "properties": {
                                        "title": {"type": "string"},
                                        "summary": {"type": "string"},
                                        "content": {"type": "string"},
                                        "tags": {"type": "array", "items": {"type": "string"}},
                                        "category": {"type": "string"},
                                        "is_published": {"type": "boolean"},
                                        "created_by": {"type": "string"},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "201": {
                            "description": "Article created",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/KnowledgeResponse"}}},
                        }
                    },
                },
            },
            "/inventory/software": {
                "get": {
                    "summary": "List software assets",
                    "tags": ["Software"],
                    "parameters": [
                        {"name": "vendor", "in": "query", "schema": {"type": "string"}},
                        {"name": "name", "in": "query", "schema": {"type": "string"}},
                    ],
                    "responses": {
                        "200": {
                            "description": "Software assets",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/SoftwareList"}}},
                        }
                    },
                },
                "post": {
                    "summary": "Create software asset",
                    "tags": ["Software"],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/SoftwareAssetInput"},
                            }
                        },
                    },
                    "responses": {
                        "201": {
                            "description": "Created",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/SoftwareResponse"}}},
                        }
                    },
                },
            },
            "/inventory/software/{asset_id}": {
                "parameters": [
                    {"name": "asset_id", "in": "path", "required": True, "schema": {"type": "integer"}}
                ],
                "get": {
                    "summary": "Retrieve software asset",
                    "tags": ["Software"],
                    "responses": {
                        "200": {
                            "description": "Asset",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/SoftwareResponse"}}},
                        },
                        "404": {"description": "Not found"},
                    },
                },
                "patch": {
                    "summary": "Update software asset",
                    "tags": ["Software"],
                    "requestBody": {
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/SoftwareAssetInput"}}
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Updated",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/SoftwareResponse"}}},
                        }
                    },
                },
                "delete": {
                    "summary": "Delete software asset",
                    "tags": ["Software"],
                    "responses": {"200": {"description": "Deleted"}, "404": {"description": "Not found"}},
                },
            },
            "/inventory/hardware": {
                "get": {
                    "summary": "List hardware assets",
                    "tags": ["Hardware"],
                    "parameters": [
                        {"name": "manufacturer", "in": "query", "schema": {"type": "string"}},
                        {"name": "category", "in": "query", "schema": {"type": "string"}},
                    ],
                    "responses": {
                        "200": {
                            "description": "Hardware assets",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/HardwareList"}}},
                        }
                    },
                },
                "post": {
                    "summary": "Create hardware asset",
                    "tags": ["Hardware"],
                    "requestBody": {
                        "required": False,
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/HardwareAssetInput"}}
                        },
                    },
                    "responses": {
                        "201": {
                            "description": "Created",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/HardwareResponse"}}},
                        }
                    },
                },
            },
            "/inventory/hardware/{asset_id}": {
                "parameters": [
                    {"name": "asset_id", "in": "path", "required": True, "schema": {"type": "integer"}}
                ],
                "get": {
                    "summary": "Retrieve hardware asset",
                    "tags": ["Hardware"],
                    "responses": {
                        "200": {
                            "description": "Asset",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/HardwareResponse"}}},
                        },
                        "404": {"description": "Not found"},
                    },
                },
                "patch": {
                    "summary": "Update hardware asset",
                    "tags": ["Hardware"],
                    "requestBody": {
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/HardwareAssetInput"}}
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Updated",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/HardwareResponse"}}},
                        }
                    },
                },
                "delete": {
                    "summary": "Delete hardware asset",
                    "tags": ["Hardware"],
                    "responses": {"200": {"description": "Deleted"}, "404": {"description": "Not found"}},
                },
            },
        },
        "components": {
            "securitySchemes": {
                "ApiKeyAuth": {
                    "type": "apiKey",
                    "name": "X-API-Key",
                    "in": "header",
                    "description": "Management generated API key. `Authorization: Bearer <key>` is also accepted.",
                }
            },
            "schemas": {
                "ApiClient": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "prefix": {"type": "string"},
                        "default_user": {"type": "string", "nullable": True},
                        "created_at": {"type": "string", "format": "date-time"},
                        "last_used_at": {"type": "string", "format": "date-time", "nullable": True},
                        "revoked_at": {"type": "string", "format": "date-time", "nullable": True},
                    },
                },
                "Ticket": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "subject": {"type": "string"},
                        "description": {"type": "string"},
                        "priority": {"type": "string"},
                        "status": {"type": "string"},
                        "department": {"type": "string"},
                        "created_by": {"type": "integer"},
                        "assigned_to": {"type": "integer", "nullable": True},
                        "created_at": {"type": "string", "format": "date-time"},
                        "updated_at": {"type": "string", "format": "date-time"},
                        "closed_at": {"type": "string", "format": "date-time", "nullable": True},
                        "assignee": {"type": "string", "nullable": True},
                    },
                },
                "TicketResponse": {
                    "type": "object",
                    "properties": {"ticket": {"$ref": "#/components/schemas/Ticket"}},
                },
                "KnowledgeArticle": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "title": {"type": "string"},
                        "summary": {"type": "string"},
                        "content": {"type": "string"},
                        "tags": {"type": "string"},
                        "category": {"type": "string"},
                        "is_published": {"type": "boolean"},
                        "created_by": {"type": "integer"},
                        "updated_by": {"type": "integer", "nullable": True},
                        "created_at": {"type": "string", "format": "date-time"},
                        "updated_at": {"type": "string", "format": "date-time"},
                        "attachments": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "integer"},
                                    "filename": {"type": "string"},
                                    "uploaded_at": {"type": "string", "format": "date-time"},
                                    "size": {"type": "integer", "nullable": True},
                                },
                            },
                        },
                    },
                },
                "KnowledgeResponse": {
                    "type": "object",
                    "properties": {"article": {"$ref": "#/components/schemas/KnowledgeArticle"}},
                },
                "SoftwareAsset": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "name": {"type": "string"},
                        "category": {"type": "string"},
                        "vendor": {"type": "string"},
                        "version": {"type": "string"},
                        "license_type": {"type": "string"},
                        "license_key": {"type": "string"},
                        "serial_number": {"type": "string"},
                        "custom_tag": {"type": "string"},
                        "seats": {"type": "integer", "nullable": True},
                        "platform": {"type": "string"},
                        "environment": {"type": "string"},
                        "status": {"type": "string"},
                        "cost_center": {"type": "string"},
                        "purchase_date": {"type": "string", "format": "date"},
                        "expiration_date": {"type": "string", "format": "date"},
                        "renewal_date": {"type": "string", "format": "date"},
                        "support_vendor": {"type": "string"},
                        "support_email": {"type": "string"},
                        "support_phone": {"type": "string"},
                        "contract_url": {"type": "string"},
                        "assigned_to": {"type": "integer", "nullable": True},
                        "assigned_to_name": {"type": "string"},
                        "assigned_on": {"type": "string", "format": "date"},
                        "usage_scope": {"type": "string"},
                        "deployment_notes": {"type": "string"},
                        "created_at": {"type": "string", "format": "date-time"},
                        "updated_at": {"type": "string", "format": "date-time"},
                    },
                },
                "SoftwareAssetInput": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "category": {"type": "string"},
                        "vendor": {"type": "string"},
                        "version": {"type": "string"},
                        "license_type": {"type": "string"},
                        "license_key": {"type": "string"},
                        "serial_number": {"type": "string"},
                        "custom_tag": {"type": "string"},
                        "seats": {"type": "integer"},
                        "platform": {"type": "string"},
                        "environment": {"type": "string"},
                        "status": {"type": "string"},
                        "cost_center": {"type": "string"},
                        "purchase_date": {"type": "string", "format": "date"},
                        "expiration_date": {"type": "string", "format": "date"},
                        "renewal_date": {"type": "string", "format": "date"},
                        "support_vendor": {"type": "string"},
                        "support_email": {"type": "string"},
                        "support_phone": {"type": "string"},
                        "contract_url": {"type": "string"},
                        "assigned_to": {"type": "string"},
                        "assigned_on": {"type": "string", "format": "date"},
                        "usage_scope": {"type": "string"},
                        "deployment_notes": {"type": "string"},
                    },
                },
                "SoftwareResponse": {
                    "type": "object",
                    "properties": {"software": {"$ref": "#/components/schemas/SoftwareAsset"}},
                },
                "SoftwareList": {
                    "type": "object",
                    "properties": {
                        "software": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/SoftwareAsset"},
                        }
                    },
                },
                "HardwareAsset": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "asset_tag": {"type": "string"},
                        "serial_number": {"type": "string"},
                        "custom_tag": {"type": "string"},
                        "category": {"type": "string"},
                        "type": {"type": "string"},
                        "manufacturer": {"type": "string"},
                        "model": {"type": "string"},
                        "cpu": {"type": "string"},
                        "ram_gb": {"type": "string"},
                        "storage": {"type": "string"},
                        "gpu": {"type": "string"},
                        "operating_system": {"type": "string"},
                        "ip_address": {"type": "string"},
                        "mac_address": {"type": "string"},
                        "hostname": {"type": "string"},
                        "location": {"type": "string"},
                        "rack": {"type": "string"},
                        "status": {"type": "string"},
                        "condition": {"type": "string"},
                        "purchase_date": {"type": "string", "format": "date"},
                        "warranty_end": {"type": "string", "format": "date"},
                        "support_vendor": {"type": "string"},
                        "support_contract": {"type": "string"},
                        "assigned_to": {"type": "integer", "nullable": True},
                        "assigned_to_name": {"type": "string"},
                        "assigned_on": {"type": "string", "format": "date"},
                        "accessories": {"type": "string"},
                        "power_supply": {"type": "string"},
                        "bios_version": {"type": "string"},
                        "firmware_version": {"type": "string"},
                        "notes": {"type": "string"},
                        "created_at": {"type": "string", "format": "date-time"},
                        "updated_at": {"type": "string", "format": "date-time"},
                    },
                },
                "HardwareAssetInput": {
                    "type": "object",
                    "properties": {
                        "asset_tag": {"type": "string"},
                        "serial_number": {"type": "string"},
                        "custom_tag": {"type": "string"},
                        "category": {"type": "string"},
                        "type": {"type": "string"},
                        "manufacturer": {"type": "string"},
                        "model": {"type": "string"},
                        "cpu": {"type": "string"},
                        "ram_gb": {"type": "string"},
                        "storage": {"type": "string"},
                        "gpu": {"type": "string"},
                        "operating_system": {"type": "string"},
                        "ip_address": {"type": "string"},
                        "mac_address": {"type": "string"},
                        "hostname": {"type": "string"},
                        "location": {"type": "string"},
                        "rack": {"type": "string"},
                        "status": {"type": "string"},
                        "condition": {"type": "string"},
                        "purchase_date": {"type": "string", "format": "date"},
                        "warranty_end": {"type": "string", "format": "date"},
                        "support_vendor": {"type": "string"},
                        "support_contract": {"type": "string"},
                        "assigned_to": {"type": "string"},
                        "assigned_on": {"type": "string", "format": "date"},
                        "accessories": {"type": "string"},
                        "power_supply": {"type": "string"},
                        "bios_version": {"type": "string"},
                        "firmware_version": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                },
                "HardwareResponse": {
                    "type": "object",
                    "properties": {"hardware": {"$ref": "#/components/schemas/HardwareAsset"}},
                },
                "HardwareList": {
                    "type": "object",
                    "properties": {
                        "hardware": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/HardwareAsset"},
                        }
                    },
                },
            },
        },
    }


def _apply_fields(model, data: dict, fields: Iterable[str], *, date_fields=None, int_fields=None):
    date_fields = set(date_fields or [])
    int_fields = set(int_fields or [])
    for field in fields:
        if field not in data:
            continue
        value = data.get(field)
        if field in date_fields:
            value = _parse_date(value)
        elif field in int_fields:
            try:
                value = int(value) if value not in (None, "") else None
            except (TypeError, ValueError):
                value = None
        setattr(model, field, value)


# ───────── Auth hooks ───────── #
@api_bp.before_request
def authenticate_api_key():
    if request.method == "OPTIONS":
        return
    if request.endpoint == "api.openapi_spec" or request.path.endswith("/openapi.json"):
        return
    key = _extract_api_key()
    client = ApiClient.verify_key(key) if key else None
    if not client:
        return _error("Valid API key required.", 401)
    g.api_client = client


@api_bp.after_request
def persist_last_used(response):
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
    return response


# ───────── Status ───────── #
@api_bp.route("/status", methods=["GET"])
def api_status():
    return jsonify(
        {
            "status": "ok",
            "timestamp": datetime.utcnow().isoformat(),
            "client": g.api_client.to_dict(),
        }
    )


# ───────── Ticket endpoints ───────── #
@api_bp.route("/tickets", methods=["GET"])
def list_tickets():
    query = Ticket.query
    status_filter = request.args.get("status")
    assigned_to = request.args.get("assigned_to")
    department = request.args.get("department")

    if status_filter:
        query = query.filter(Ticket.status.ilike(status_filter))
    if department:
        query = query.filter(Ticket.department.ilike(department))
    if assigned_to:
        user = _resolve_user(assigned_to, allow_default=False)
        if not user:
            return _error("Assigned user not found.", 404)
        query = query.filter(Ticket.assigned_to == user.id)

    tickets = query.order_by(Ticket.created_at.desc()).all()
    return jsonify({"tickets": [_ticket_to_dict(t) for t in tickets]})


@api_bp.route("/tickets", methods=["POST"])
def create_ticket():
    payload = request.get_json(silent=True) or {}
    subject = (payload.get("subject") or "").strip()
    description = (payload.get("description") or "").strip()
    if not subject or not description:
        return _error("Both subject and description are required.")

    creator = _resolve_user(payload.get("created_by"))
    if not creator:
        return _error("created_by must reference a valid user or configure a default user for this API key.", 400)

    ticket = Ticket(
        subject=subject,
        description=description,
        priority=payload.get("priority"),
        status=payload.get("status") or "Open",
        department=payload.get("department"),
        created_by=creator.id,
    )

    assignee_ref = payload.get("assigned_to")
    if assignee_ref:
        assignee = _resolve_user(assignee_ref, allow_default=False)
        if not assignee:
            return _error("assigned_to user not found.", 404)
        ticket.assigned_to = assignee.id

    db.session.add(ticket)
    db.session.commit()
    return jsonify({"ticket": _ticket_to_dict(ticket)}), 201


@api_bp.route("/tickets/<int:ticket_id>", methods=["GET"])
def get_ticket(ticket_id: int):
    ticket = Ticket.query.get_or_404(ticket_id)
    return jsonify({"ticket": _ticket_to_dict(ticket)})


@api_bp.route("/tickets/<int:ticket_id>", methods=["PUT", "PATCH"])
def update_ticket(ticket_id: int):
    ticket = Ticket.query.get_or_404(ticket_id)
    payload = request.get_json(silent=True) or {}

    for field in ("subject", "description", "priority", "status", "department"):
        if field in payload:
            value = payload.get(field)
            if isinstance(value, str):
                value = value.strip()
            setattr(ticket, field, value)

    if "assigned_to" in payload:
        assignee = _resolve_user(payload.get("assigned_to"), allow_default=False)
        ticket.assigned_to = assignee.id if assignee else None

    if "closed_at" in payload:
        ticket.closed_at = datetime.fromisoformat(payload["closed_at"]) if payload["closed_at"] else None

    db.session.add(ticket)
    db.session.commit()
    return jsonify({"ticket": _ticket_to_dict(ticket)})


@api_bp.route("/tickets/<int:ticket_id>", methods=["DELETE"])
def delete_ticket(ticket_id: int):
    ticket = Ticket.query.get_or_404(ticket_id)
    db.session.delete(ticket)
    db.session.commit()
    return jsonify({"status": "deleted", "id": ticket_id}), 200


# ───────── Knowledge endpoints ───────── #
@api_bp.route("/knowledge", methods=["GET"])
def search_knowledge():
    query_param = (request.args.get("q") or "").strip()
    if not query_param:
        return _error("Parameter 'q' is required.", 400)

    like_term = f"%{query_param}%"
    query = (
        KnowledgeArticle.query.outerjoin(
            KnowledgeAttachment,
            KnowledgeAttachment.article_id == KnowledgeArticle.id,
        )
        .filter(
            or_(
                KnowledgeArticle.title.ilike(like_term),
                KnowledgeArticle.summary.ilike(like_term),
                KnowledgeArticle.content.ilike(like_term),
                KnowledgeArticle.tags.ilike(like_term),
                KnowledgeArticle.category.ilike(like_term),
                KnowledgeAttachment.original_filename.ilike(like_term),
                KnowledgeAttachment.extracted_text.ilike(like_term),
            )
        )
        .filter(KnowledgeArticle.is_published.is_(True))
        .distinct()
        .order_by(KnowledgeArticle.updated_at.desc())
        .limit(50)
    )

    return jsonify({"results": [_knowledge_to_dict(article) for article in query.all()]})


@api_bp.route("/knowledge", methods=["POST"])
def create_article():
    payload = request.get_json(silent=True) or {}
    title = (payload.get("title") or "").strip()
    content = (payload.get("content") or "").strip()
    if not title or not content:
        return _error("title and content are required.")

    author = _resolve_user(payload.get("created_by"))
    if not author:
        return _error("created_by must reference a valid user or configure a default user for this API key.", 400)

    tags = payload.get("tags")
    if isinstance(tags, list):
        tags = ",".join(tag.strip() for tag in tags if tag)

    article = KnowledgeArticle(
        title=title,
        summary=payload.get("summary"),
        content=content,
        tags=tags,
        category=payload.get("category"),
        is_published=bool(payload.get("is_published", True)),
        created_by=author.id,
        updated_by=author.id,
    )
    db.session.add(article)
    db.session.flush()
    article.add_version(author.id)
    db.session.commit()
    return jsonify({"article": _knowledge_to_dict(article)}), 201


# ───────── Software inventory endpoints ───────── #
SOFTWARE_FIELDS = {
    "name",
    "category",
    "vendor",
    "version",
    "license_type",
    "license_key",
    "serial_number",
    "custom_tag",
    "seats",
    "platform",
    "environment",
    "status",
    "cost_center",
    "purchase_date",
    "expiration_date",
    "renewal_date",
    "support_vendor",
    "support_email",
    "support_phone",
    "contract_url",
    "assigned_on",
    "usage_scope",
    "deployment_notes",
}
SOFTWARE_DATE_FIELDS = {"purchase_date", "expiration_date", "renewal_date", "assigned_on"}
SOFTWARE_INT_FIELDS = {"seats"}


def _apply_software_fields(asset: SoftwareAsset, payload: dict):
    _apply_fields(
        asset,
        payload,
        SOFTWARE_FIELDS,
        date_fields=SOFTWARE_DATE_FIELDS,
        int_fields=SOFTWARE_INT_FIELDS,
    )
    if "assigned_to" in payload:
        user = _resolve_user(payload.get("assigned_to"), allow_default=False)
        asset.assigned_to = user.id if user else None


@api_bp.route("/inventory/software", methods=["GET"])
def list_software():
    query = SoftwareAsset.query
    vendor = request.args.get("vendor")
    name = request.args.get("name")
    if vendor:
        query = query.filter(SoftwareAsset.vendor.ilike(f"%{vendor}%"))
    if name:
        query = query.filter(SoftwareAsset.name.ilike(f"%{name}%"))
    assets = query.order_by(SoftwareAsset.updated_at.desc()).limit(200).all()
    return jsonify({"software": [_software_to_dict(asset) for asset in assets]})


@api_bp.route("/inventory/software", methods=["POST"])
def create_software():
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        return _error("name is required.")
    asset = SoftwareAsset(name=name)
    _apply_software_fields(asset, payload)
    db.session.add(asset)
    db.session.commit()
    return jsonify({"software": _software_to_dict(asset)}), 201


@api_bp.route("/inventory/software/<int:asset_id>", methods=["GET"])
def get_software(asset_id: int):
    asset = SoftwareAsset.query.get_or_404(asset_id)
    return jsonify({"software": _software_to_dict(asset)})


@api_bp.route("/inventory/software/<int:asset_id>", methods=["PUT", "PATCH"])
def update_software(asset_id: int):
    asset = SoftwareAsset.query.get_or_404(asset_id)
    payload = request.get_json(silent=True) or {}
    if "name" in payload and not (payload.get("name") or "").strip():
        return _error("name cannot be blank.")
    _apply_software_fields(asset, payload)
    db.session.add(asset)
    db.session.commit()
    return jsonify({"software": _software_to_dict(asset)})


@api_bp.route("/inventory/software/<int:asset_id>", methods=["DELETE"])
def delete_software(asset_id: int):
    asset = SoftwareAsset.query.get_or_404(asset_id)
    db.session.delete(asset)
    db.session.commit()
    return jsonify({"status": "deleted", "id": asset_id}), 200


# ───────── Hardware inventory endpoints ───────── #
HARDWARE_FIELDS = {
    "asset_tag",
    "serial_number",
    "custom_tag",
    "category",
    "type",
    "manufacturer",
    "model",
    "cpu",
    "ram_gb",
    "storage",
    "gpu",
    "operating_system",
    "ip_address",
    "mac_address",
    "hostname",
    "location",
    "rack",
    "status",
    "condition",
    "purchase_date",
    "warranty_end",
    "support_vendor",
    "support_contract",
    "assigned_on",
    "accessories",
    "power_supply",
    "bios_version",
    "firmware_version",
    "notes",
}
HARDWARE_DATE_FIELDS = {"purchase_date", "warranty_end", "assigned_on"}


def _apply_hardware_fields(asset: HardwareAsset, payload: dict):
    _apply_fields(
        asset,
        payload,
        HARDWARE_FIELDS,
        date_fields=HARDWARE_DATE_FIELDS,
    )
    if "assigned_to" in payload:
        user = _resolve_user(payload.get("assigned_to"), allow_default=False)
        asset.assigned_to = user.id if user else None


@api_bp.route("/inventory/hardware", methods=["GET"])
def list_hardware():
    query = HardwareAsset.query
    manufacturer = request.args.get("manufacturer")
    category = request.args.get("category")
    if manufacturer:
        query = query.filter(HardwareAsset.manufacturer.ilike(f"%{manufacturer}%"))
    if category:
        query = query.filter(HardwareAsset.category.ilike(f"%{category}%"))
    assets = query.order_by(HardwareAsset.updated_at.desc()).limit(200).all()
    return jsonify({"hardware": [_hardware_to_dict(asset) for asset in assets]})


@api_bp.route("/inventory/hardware", methods=["POST"])
def create_hardware():
    payload = request.get_json(silent=True) or {}
    asset = HardwareAsset()
    _apply_hardware_fields(asset, payload)
    db.session.add(asset)
    db.session.commit()
    return jsonify({"hardware": _hardware_to_dict(asset)}), 201


@api_bp.route("/inventory/hardware/<int:asset_id>", methods=["GET"])
def get_hardware(asset_id: int):
    asset = HardwareAsset.query.get_or_404(asset_id)
    return jsonify({"hardware": _hardware_to_dict(asset)})


@api_bp.route("/inventory/hardware/<int:asset_id>", methods=["PUT", "PATCH"])
def update_hardware(asset_id: int):
    asset = HardwareAsset.query.get_or_404(asset_id)
    payload = request.get_json(silent=True) or {}
    _apply_hardware_fields(asset, payload)
    db.session.add(asset)
    db.session.commit()
    return jsonify({"hardware": _hardware_to_dict(asset)})


@api_bp.route("/inventory/hardware/<int:asset_id>", methods=["DELETE"])
def delete_hardware(asset_id: int):
    asset = HardwareAsset.query.get_or_404(asset_id)
    db.session.delete(asset)
    db.session.commit()
    return jsonify({"status": "deleted", "id": asset_id}), 200


@api_bp.route("/openapi.json", methods=["GET"])
def openapi_spec():
    return jsonify(_build_openapi_spec())
