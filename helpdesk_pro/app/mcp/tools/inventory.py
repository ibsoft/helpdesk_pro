"""
Inventory-related MCP tools.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator

from ..db import fetch_all
from .base import BaseTool, ToolExecutionError


def _clean_str_list(value: Optional[List[str]]) -> Optional[List[str]]:
    if not value:
        return None
    cleaned = [item.strip() for item in value if item and item.strip()]
    return cleaned or None


class HardwareSummaryArgs(BaseModel):
    status: Optional[List[str]] = Field(
        default=None, description="Optional list of hardware status values to include."
    )
    category: Optional[List[str]] = Field(
        default=None, description="Optional list of hardware categories to include."
    )
    location_contains: Optional[str] = Field(
        default=None,
        description="Case-insensitive substring filter applied to the location field.",
    )
    assigned: Optional[bool] = Field(
        default=None, description="When set, filters to assigned (true) or unassigned (false) assets."
    )

    @validator("status", "category")
    def _validate_lists(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        return _clean_str_list(value)

    @validator("location_contains")
    def _strip_location(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() or None if value else None


class HardwareStatusCount(BaseModel):
    status: str
    count: int


class HardwareAssignmentCount(BaseModel):
    state: str
    count: int


class HardwareTopLocation(BaseModel):
    location: str
    count: int


class HardwareSummaryResult(BaseModel):
    total: int
    by_status: List[HardwareStatusCount]
    assignment: List[HardwareAssignmentCount]
    top_locations: List[HardwareTopLocation]


class HardwareSummaryTool(BaseTool[HardwareSummaryArgs, HardwareSummaryResult]):
    name = "hardware_summary"
    description = "Summarise hardware assets by status, assignment, and top locations."
    input_model = HardwareSummaryArgs
    output_model = HardwareSummaryResult

    async def _run(self, arguments: HardwareSummaryArgs) -> Dict[str, Any]:
        conditions = ["1=1"]
        params: Dict[str, Any] = {}

        if arguments.status:
            conditions.append("h.status = ANY(:status_list)")
            params["status_list"] = arguments.status
        if arguments.category:
            conditions.append("h.category = ANY(:category_list)")
            params["category_list"] = arguments.category
        if arguments.location_contains:
            conditions.append("h.location ILIKE :location_search")
            params["location_search"] = f"%{arguments.location_contains}%"
        if arguments.assigned is not None:
            if arguments.assigned:
                conditions.append("h.assigned_to IS NOT NULL")
            else:
                conditions.append("h.assigned_to IS NULL")

        where_clause = " AND ".join(conditions)

        total_rows = await fetch_all(
            f"""
            SELECT COUNT(*) AS total
            FROM hardware_asset AS h
            WHERE {where_clause}
            """,
            params,
        )
        total = int(total_rows[0]["total"]) if total_rows else 0

        status_rows = await fetch_all(
            f"""
            SELECT
                COALESCE(NULLIF(TRIM(h.status), ''), 'unspecified') AS status,
                COUNT(*) AS count
            FROM hardware_asset AS h
            WHERE {where_clause}
            GROUP BY COALESCE(NULLIF(TRIM(h.status), ''), 'unspecified')
            ORDER BY count DESC, status ASC
            """,
            params,
        )

        assignment_rows = await fetch_all(
            f"""
            SELECT
                CASE WHEN h.assigned_to IS NULL THEN 'unassigned' ELSE 'assigned' END AS assignment_state,
                COUNT(*) AS count
            FROM hardware_asset AS h
            WHERE {where_clause}
            GROUP BY CASE WHEN h.assigned_to IS NULL THEN 'unassigned' ELSE 'assigned' END
            ORDER BY assignment_state ASC
            """,
            params,
        )

        location_rows = await fetch_all(
            f"""
            SELECT
                COALESCE(NULLIF(TRIM(h.location), ''), 'Unspecified') AS location,
                COUNT(*) AS count
            FROM hardware_asset AS h
            WHERE {where_clause}
            GROUP BY COALESCE(NULLIF(TRIM(h.location), ''), 'Unspecified')
            ORDER BY count DESC, location ASC
            LIMIT 10
            """,
            params,
        )

        return {
            "total": total,
            "by_status": [
                {"status": row["status"], "count": int(row["count"])} for row in status_rows
            ],
            "assignment": [
                {"state": row["assignment_state"], "count": int(row["count"])}
                for row in assignment_rows
            ],
            "top_locations": [
                {"location": row["location"], "count": int(row["count"])}
                for row in location_rows
            ],
        }


class SoftwareRenewalsArgs(BaseModel):
    window_days: int = Field(
        60,
        ge=1,
        le=365,
        description="Number of days ahead to check for software renewals.",
    )
    limit: int = Field(
        50,
        ge=1,
        le=500,
        description="Maximum number of software assets to return.",
    )
    include_overdue: bool = Field(
        False,
        description="Include renewals that are overdue by up to the same window.",
    )
    status: Optional[List[str]] = Field(
        default=None, description="Optional list of software status values to include."
    )
    vendor: Optional[str] = Field(
        default=None,
        description="Optional vendor name filter (case-insensitive substring).",
    )
    environment: Optional[str] = Field(
        default=None,
        description="Optional environment filter (exact match).",
    )

    @validator("status")
    def _validate_status(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        return _clean_str_list(value)

    @validator("vendor", "environment")
    def _strip_optional(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() or None if value else None


class SoftwareRenewalRow(BaseModel):
    asset_id: int
    name: str
    vendor: Optional[str]
    status: Optional[str]
    environment: Optional[str]
    renewal_date: str
    days_until_renewal: int
    license_type: Optional[str]
    assigned_to: Optional[int]
    assigned_to_username: Optional[str]


class SoftwareRenewalsResult(BaseModel):
    window_days: int
    include_overdue: bool
    rows: List[SoftwareRenewalRow]


class SoftwareRenewalsTool(BaseTool[SoftwareRenewalsArgs, SoftwareRenewalsResult]):
    name = "software_renewals"
    description = "List software assets with upcoming renewal dates."
    input_model = SoftwareRenewalsArgs
    output_model = SoftwareRenewalsResult

    async def _run(self, arguments: SoftwareRenewalsArgs) -> Dict[str, Any]:
        if arguments.window_days <= 0:
            raise ToolExecutionError("window_days must be positive.")

        params: Dict[str, Any] = {
            "window_days": arguments.window_days,
            "limit": arguments.limit,
        }
        conditions = ["sa.renewal_date IS NOT NULL"]

        lower_bound = "CURRENT_DATE"
        if arguments.include_overdue:
            lower_bound = "(CURRENT_DATE - (INTERVAL '1 day' * :window_days))"
        conditions.append(
            f"sa.renewal_date BETWEEN {lower_bound} AND (CURRENT_DATE + (INTERVAL '1 day' * :window_days))"
        )

        if arguments.status:
            conditions.append("sa.status = ANY(:status_list)")
            params["status_list"] = arguments.status
        if arguments.vendor:
            conditions.append("sa.vendor ILIKE :vendor_name")
            params["vendor_name"] = f"%{arguments.vendor}%"
        if arguments.environment:
            conditions.append("sa.environment = :environment")
            params["environment"] = arguments.environment

        where_clause = " AND ".join(conditions)

        rows = await fetch_all(
            f"""
            SELECT
                sa.id,
                sa.name,
                sa.vendor,
                sa.status,
                sa.environment,
                sa.renewal_date,
                sa.license_type,
                sa.assigned_to,
                u.username AS assigned_to_username
            FROM software_asset AS sa
            LEFT JOIN "user" AS u ON u.id = sa.assigned_to
            WHERE {where_clause}
            ORDER BY sa.renewal_date ASC, sa.name ASC
            LIMIT :limit
            """,
            params,
        )

        today = date.today()
        result_rows: List[Dict[str, Any]] = []
        for row in rows:
            renewal_date_value = row.get("renewal_date")
            if not isinstance(renewal_date_value, (datetime, date)):
                continue
            # Convert datetime to date for consistent calculations.
            if isinstance(renewal_date_value, datetime):
                renewal_date = renewal_date_value.date()
            else:
                renewal_date = renewal_date_value
            days_until = (renewal_date - today).days
            result_rows.append(
                {
                    "asset_id": row["id"],
                    "name": row["name"],
                    "vendor": row.get("vendor"),
                    "status": row.get("status"),
                    "environment": row.get("environment"),
                    "renewal_date": renewal_date.isoformat(),
                    "days_until_renewal": days_until,
                    "license_type": row.get("license_type"),
                    "assigned_to": row.get("assigned_to"),
                    "assigned_to_username": row.get("assigned_to_username"),
                }
            )

        return {
            "window_days": arguments.window_days,
            "include_overdue": arguments.include_overdue,
            "rows": result_rows,
        }


__all__ = [
    "HardwareSummaryTool",
    "SoftwareRenewalsTool",
]
