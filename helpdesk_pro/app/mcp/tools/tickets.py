"""
Ticket-related MCP tools.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator

from ..db import fetch_all
from .base import BaseTool, ToolExecutionError


def _clean_str_list(value: Optional[List[str]]) -> Optional[List[str]]:
    if not value:
        return None
    cleaned = [item.strip() for item in value if item and item.strip()]
    return cleaned or None


class TicketQueueSummaryArgs(BaseModel):
    statuses: Optional[List[str]] = Field(
        default=None,
        description="Restrict to specific ticket statuses.",
    )
    priorities: Optional[List[str]] = Field(
        default=None,
        description="Restrict to specific ticket priorities.",
    )
    department: Optional[str] = Field(
        default=None,
        description="Filter by owning department (exact match, case-insensitive).",
    )
    include_closed: bool = Field(
        False,
        description="Include closed/resolved tickets in the summary.",
    )
    assigned_only: bool = Field(
        False,
        description="When true, only include tickets that have an assignee.",
    )
    unassigned_only: bool = Field(
        False,
        description="When true, only include tickets without an assignee.",
    )
    overdue_hours: int = Field(
        72,
        ge=1,
        le=7 * 24,
        description="Threshold in hours for counting overdue tickets.",
    )

    @validator("statuses", "priorities")
    def _validate_list_fields(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        return _clean_str_list(value)

    @validator("department")
    def _strip_department(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() or None if value else None

    @validator("unassigned_only")
    def _validate_assignment_flags(cls, value: bool, values: Dict[str, Any]) -> bool:
        if value and values.get("assigned_only"):
            raise ValueError("assigned_only and unassigned_only cannot both be true.")
        return value


class TicketStatusCount(BaseModel):
    status: str
    count: int


class TicketPriorityCount(BaseModel):
    priority: str
    count: int


class TicketQueueSummaryResult(BaseModel):
    total: int
    overdue_count: int
    average_age_hours: Optional[float]
    by_status: List[TicketStatusCount]
    by_priority: List[TicketPriorityCount]


class TicketQueueSummaryTool(BaseTool[TicketQueueSummaryArgs, TicketQueueSummaryResult]):
    name = "ticket_queue_summary"
    description = "Summarise ticket queue volume by status and priority with aging metrics."
    input_model = TicketQueueSummaryArgs
    output_model = TicketQueueSummaryResult

    async def _run(self, arguments: TicketQueueSummaryArgs) -> Dict[str, Any]:
        conditions = ["1=1"]
        params: Dict[str, Any] = {}

        if arguments.statuses:
            conditions.append("LOWER(t.status) = ANY(:status_list)")
            params["status_list"] = [status.lower() for status in arguments.statuses]
        elif not arguments.include_closed:
            conditions.append("LOWER(t.status) NOT IN ('closed', 'resolved')")

        if arguments.priorities:
            conditions.append("LOWER(t.priority) = ANY(:priority_list)")
            params["priority_list"] = [priority.lower() for priority in arguments.priorities]

        if arguments.department:
            conditions.append("LOWER(t.department) = LOWER(:department)")
            params["department"] = arguments.department

        if arguments.assigned_only:
            conditions.append("t.assigned_to IS NOT NULL")
        if arguments.unassigned_only:
            conditions.append("t.assigned_to IS NULL")

        where_clause = " AND ".join(conditions)

        total_rows = await fetch_all(
            f"SELECT COUNT(*) AS total FROM ticket AS t WHERE {where_clause}",
            params,
        )
        total = int(total_rows[0]["total"]) if total_rows else 0

        status_rows = await fetch_all(
            f"""
            SELECT
                COALESCE(NULLIF(TRIM(t.status), ''), 'unspecified') AS status,
                COUNT(*) AS count
            FROM ticket AS t
            WHERE {where_clause}
            GROUP BY COALESCE(NULLIF(TRIM(t.status), ''), 'unspecified')
            ORDER BY count DESC, status ASC
            """,
            params,
        )

        priority_rows = await fetch_all(
            f"""
            SELECT
                COALESCE(NULLIF(TRIM(t.priority), ''), 'unspecified') AS priority,
                COUNT(*) AS count
            FROM ticket AS t
            WHERE {where_clause}
            GROUP BY COALESCE(NULLIF(TRIM(t.priority), ''), 'unspecified')
            ORDER BY count DESC, priority ASC
            """,
            params,
        )

        avg_age_rows = await fetch_all(
            f"""
            SELECT
                AVG(EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - COALESCE(t.created_at, CURRENT_TIMESTAMP)))) / 3600.0
                    AS avg_age_hours
            FROM ticket AS t
            WHERE {where_clause}
            """,
            params,
        )
        average_age_hours = avg_age_rows[0]["avg_age_hours"] if avg_age_rows and avg_age_rows[0]["avg_age_hours"] is not None else None

        overdue_params = dict(params)
        overdue_params["overdue_hours"] = arguments.overdue_hours
        overdue_rows = await fetch_all(
            f"""
            SELECT COUNT(*) AS count
            FROM ticket AS t
            WHERE {where_clause}
              AND (
                  CURRENT_TIMESTAMP - COALESCE(t.created_at, CURRENT_TIMESTAMP)
                  > (INTERVAL '1 hour' * :overdue_hours)
              )
            """,
            overdue_params,
        )
        overdue_count = int(overdue_rows[0]["count"]) if overdue_rows else 0

        return {
            "total": total,
            "overdue_count": overdue_count,
            "average_age_hours": float(average_age_hours) if average_age_hours is not None else None,
            "by_status": [
                {"status": row["status"], "count": int(row["count"])} for row in status_rows
            ],
            "by_priority": [
                {"priority": row["priority"], "count": int(row["count"])} for row in priority_rows
            ],
        }


class TicketSlaAlertsArgs(BaseModel):
    age_hours: int = Field(
        48,
        ge=1,
        le=14 * 24,
        description="Minimum ticket age (in hours) to include.",
    )
    statuses_exclude: Optional[List[str]] = Field(
        default_factory=lambda: ["closed", "resolved"],
        description="Statuses to exclude when identifying aged tickets.",
    )
    department: Optional[str] = Field(
        default=None,
        description="Filter by department (case-insensitive exact match).",
    )
    limit: int = Field(
        50,
        ge=1,
        le=500,
        description="Maximum number of tickets to return.",
    )

    @validator("statuses_exclude")
    def _validate_statuses_exclude(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        return _clean_str_list(value)

    @validator("department")
    def _strip_department(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() or None if value else None


class TicketAlertRow(BaseModel):
    ticket_id: int
    subject: str
    status: Optional[str]
    priority: Optional[str]
    department: Optional[str]
    created_at: str
    age_hours: float
    assigned_to: Optional[int]


class TicketSlaAlertsResult(BaseModel):
    age_hours: int
    rows: List[TicketAlertRow]


class TicketSlaAlertsTool(BaseTool[TicketSlaAlertsArgs, TicketSlaAlertsResult]):
    name = "ticket_sla_alerts"
    description = "List tickets exceeding a specified age threshold to surface potential SLA breaches."
    input_model = TicketSlaAlertsArgs
    output_model = TicketSlaAlertsResult

    async def _run(self, arguments: TicketSlaAlertsArgs) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "age_hours": arguments.age_hours,
            "limit": arguments.limit,
        }
        conditions = [
            "(CURRENT_TIMESTAMP - COALESCE(t.created_at, CURRENT_TIMESTAMP)) >= (INTERVAL '1 hour' * :age_hours)"
        ]

        if arguments.statuses_exclude:
            params["statuses_exclude"] = [status.lower() for status in arguments.statuses_exclude]
            conditions.append("LOWER(t.status) <> ALL(:statuses_exclude)")

        if arguments.department:
            params["department"] = arguments.department
            conditions.append("LOWER(t.department) = LOWER(:department)")

        where_clause = " AND ".join(conditions)

        rows = await fetch_all(
            f"""
            SELECT
                t.id,
                t.subject,
                t.status,
                t.priority,
                t.department,
                t.created_at,
                t.assigned_to,
                EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - COALESCE(t.created_at, CURRENT_TIMESTAMP))) / 3600.0 AS age_hours
            FROM ticket AS t
            WHERE {where_clause}
            ORDER BY age_hours DESC, t.id ASC
            LIMIT :limit
            """,
            params,
        )

        results: List[Dict[str, Any]] = []
        for row in rows:
            created_at_value = row.get("created_at")
            created_at_iso = None
            if isinstance(created_at_value, datetime):
                if created_at_value.tzinfo is None:
                    created_at_iso = created_at_value.replace(tzinfo=timezone.utc).isoformat()
                else:
                    created_at_iso = created_at_value.astimezone(timezone.utc).isoformat()
            results.append(
                {
                    "ticket_id": row["id"],
                    "subject": row["subject"],
                    "status": row.get("status"),
                    "priority": row.get("priority"),
                    "department": row.get("department"),
                    "created_at": created_at_iso,
                    "age_hours": float(row.get("age_hours") or 0.0),
                    "assigned_to": row.get("assigned_to"),
                }
            )

        return {
            "age_hours": arguments.age_hours,
            "rows": results,
        }


__all__ = [
    "TicketQueueSummaryTool",
    "TicketSlaAlertsTool",
]
