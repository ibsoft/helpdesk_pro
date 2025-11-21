"""Shared helpers for capturing and restoring ticket archives."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from app.models.ticket import Ticket, TicketArchive


def serialize_comments(ticket: Ticket) -> List[Dict[str, Any]]:
    data: List[Dict[str, Any]] = []
    for comment in getattr(ticket, "comments", []) or []:
        data.append(
            {
                "user": comment.user,
                "comment": comment.comment,
                "created_at": comment.created_at.isoformat() if comment.created_at else None,
            }
        )
    return data


def serialize_attachments(ticket: Ticket) -> List[Dict[str, Any]]:
    data: List[Dict[str, Any]] = []
    for attachment in getattr(ticket, "attachments", []) or []:
        data.append(
            {
                "filename": attachment.filename,
                "filepath": attachment.filepath,
                "uploaded_by": attachment.uploaded_by,
                "uploaded_at": attachment.uploaded_at.isoformat() if attachment.uploaded_at else None,
            }
        )
    return data


def serialize_logs(ticket: Ticket) -> List[Dict[str, Any]]:
    data: List[Dict[str, Any]] = []
    for log in getattr(ticket, "logs", []) or []:
        data.append(
            {
                "action": log.action,
                "username": log.username,
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
            }
        )
    return data


def build_archive_from_ticket(ticket: Ticket, archived_by_id: int | None) -> TicketArchive:
    """Create a TicketArchive ORM object from an in-memory ticket snapshot."""
    return TicketArchive(
        ticket_id=ticket.id,
        subject=ticket.subject,
        description=ticket.description,
        priority=ticket.priority,
        status=ticket.status,
        department=ticket.department,
        created_by=ticket.created_by,
        assigned_to=ticket.assigned_to,
        created_at=ticket.created_at or datetime.utcnow(),
        updated_at=ticket.updated_at or datetime.utcnow(),
        closed_at=ticket.closed_at,
        archived_at=datetime.utcnow(),
        archived_by=archived_by_id,
        comments=serialize_comments(ticket),
        attachments=serialize_attachments(ticket),
        logs=serialize_logs(ticket),
    )
