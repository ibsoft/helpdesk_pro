"""
Backup-related MCP tools.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator

from sqlalchemy.exc import ProgrammingError

from ..db import fetch_all
from .base import BaseTool, ToolExecutionError


def _clean_str_list(value: Optional[List[str]]) -> Optional[List[str]]:
    if not value:
        return None
    cleaned = [item.strip() for item in value if item and item.strip()]
    return cleaned or None


class BackupTapeSummaryArgs(BaseModel):
    status: Optional[List[str]] = Field(
        default=None,
        description="Optional list of tape statuses to include.",
    )
    medium_type: Optional[List[str]] = Field(
        default=None,
        description="Filter by medium type (e.g. tape, disk).",
    )
    location_type: Optional[List[str]] = Field(
        default=None,
        description="Filter by current location type. Use 'unassigned' for tapes without a location.",
    )
    stale_inventory_days: int = Field(
        90,
        ge=1,
        le=365,
        description="Number of days after which inventory is considered stale.",
    )

    @validator("status", "medium_type", "location_type")
    def _validate_lists(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        return _clean_str_list(value)


class TapeStatusCount(BaseModel):
    status: str
    count: int


class TapeLocationCount(BaseModel):
    location_type: str
    count: int


class BackupTapeSummaryResult(BaseModel):
    total: int
    stale_inventory_count: int
    by_status: List[TapeStatusCount]
    by_location: List[TapeLocationCount]


class BackupTapeSummaryTool(BaseTool[BackupTapeSummaryArgs, BackupTapeSummaryResult]):
    name = "backup_tape_summary"
    description = "Summarise backup media inventory by status and location."
    input_model = BackupTapeSummaryArgs
    output_model = BackupTapeSummaryResult

    async def _run(self, arguments: BackupTapeSummaryArgs) -> Dict[str, Any]:
        conditions = ["1=1"]
        params: Dict[str, Any] = {}

        if arguments.status:
            conditions.append("t.status = ANY(:status_list)")
            params["status_list"] = arguments.status

        if arguments.medium_type:
            valid_mediums = {"tape", "disk"}
            mediums = [value for value in arguments.medium_type if value in valid_mediums]
            if not mediums:
                raise ToolExecutionError("No valid medium_type values provided.")
            conditions.append("t.medium_type = ANY(:medium_list)")
            params["medium_list"] = mediums

        location_filter_clause = ""
        if arguments.location_type:
            normalized = {value for value in arguments.location_type}
            bind_required = [value for value in normalized if value != "unassigned"]
            parts = []
            if bind_required:
                parts.append("loc.location_type = ANY(:location_list)")
                params["location_list"] = bind_required
            if "unassigned" in normalized:
                parts.append("loc.location_type IS NULL")
            if not parts:
                raise ToolExecutionError("No valid location_type values provided.")
            location_filter_clause = f" AND ({' OR '.join(parts)})"

        base_where = " AND ".join(conditions)
        base_from = f"""
            FROM backup_tape_cartridge AS t
            LEFT JOIN backup_tape_location AS loc ON loc.id = t.current_location_id
            WHERE {base_where}{location_filter_clause}
        """

        total_rows = await fetch_all(f"SELECT COUNT(*) AS total {base_from}", params)
        total = int(total_rows[0]["total"]) if total_rows else 0

        status_rows = await fetch_all(
            f"""
            SELECT
                COALESCE(t.status, 'unknown') AS status,
                COUNT(*) AS count
            {base_from}
            GROUP BY COALESCE(t.status, 'unknown')
            ORDER BY count DESC, status ASC
            """,
            params,
        )

        location_rows = await fetch_all(
            f"""
            SELECT
                COALESCE(loc.location_type, 'unassigned') AS location_type,
                COUNT(*) AS count
            {base_from}
            GROUP BY COALESCE(loc.location_type, 'unassigned')
            ORDER BY count DESC, location_type ASC
            """,
            params,
        )

        stale_params = dict(params)
        stale_params["stale_days"] = arguments.stale_inventory_days
        stale_rows = await fetch_all(
            f"""
            SELECT COUNT(*) AS count
            {base_from}
              AND (
                  t.last_inventory_at IS NULL
                  OR t.last_inventory_at < (CURRENT_TIMESTAMP - (INTERVAL '1 day' * :stale_days))
              )
            """,
            stale_params,
        )
        stale_total = int(stale_rows[0]["count"]) if stale_rows else 0

        return {
            "total": total,
            "stale_inventory_count": stale_total,
            "by_status": [
                {"status": row["status"], "count": int(row["count"])} for row in status_rows
            ],
            "by_location": [
                {
                    "location_type": row["location_type"],
                    "count": int(row["count"]),
                }
                for row in location_rows
            ],
        }


class BackupJobsExpiringArgs(BaseModel):
    window_days: int = Field(
        30,
        ge=1,
        le=3650,
        description="Number of days ahead to look for expiring backup jobs (up to 10 years).",
    )
    limit: int = Field(
        50,
        ge=1,
        le=500,
        description="Maximum number of backup jobs to return.",
    )
    source_system: Optional[str] = Field(
        default=None,
        description="Optional filter for source system (case-insensitive substring match).",
    )
    verify_result: Optional[str] = Field(
        default=None,
        description="Optional filter for verification result (exact match).",
    )

    @validator("source_system", "verify_result")
    def _strip_optional(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() or None if value else None


class BackupJobRow(BaseModel):
    job_id: int
    name: str
    job_date: Optional[str]
    retention_days: Optional[int]
    expires_at: str
    days_until_expiry: int
    total_files: Optional[int]
    total_size_bytes: Optional[int]
    verify_result: Optional[str]
    source_system: Optional[str]
    tape_barcodes: List[str]


class BackupJobsExpiringResult(BaseModel):
    window_days: int
    rows: List[BackupJobRow]


class BackupJobsExpiringTool(BaseTool[BackupJobsExpiringArgs, BackupJobsExpiringResult]):
    name = "backup_jobs_expiring"
    description = "List backup jobs whose retention period expires soon."
    input_model = BackupJobsExpiringArgs
    output_model = BackupJobsExpiringResult

    async def _run(self, arguments: BackupJobsExpiringArgs) -> Dict[str, Any]:
        conditions = [
            "scoped.effective_expiry BETWEEN CURRENT_TIMESTAMP AND (CURRENT_TIMESTAMP + (INTERVAL '1 day' * :window_days))"
        ]
        params: Dict[str, Any] = {
            "window_days": arguments.window_days,
            "limit": arguments.limit,
        }

        if arguments.source_system:
            conditions.append("scoped.source_system ILIKE :source_system")
            params["source_system"] = f"%{arguments.source_system}%"
        if arguments.verify_result:
            conditions.append("scoped.verify_result = :verify_result")
            params["verify_result"] = arguments.verify_result

        where_clause = " AND ".join(conditions)

        try:
            rows = await fetch_all(
                f"""
            WITH scoped AS (
                SELECT
                    j.id,
                    j.name,
                    j.job_date,
                    j.retention_days,
                    j.expires_at,
                    j.total_files,
                    j.total_size_bytes,
                    j.verify_result,
                    j.source_system,
                    COALESCE(
                        j.expires_at,
                        CASE
                            WHEN j.job_date IS NOT NULL AND j.retention_days IS NOT NULL
                                THEN j.job_date + (INTERVAL '1 day' * j.retention_days)
                            ELSE NULL
                        END
                    ) AS effective_expiry
                FROM backup_job AS j
            )
            SELECT
                scoped.id,
                scoped.name,
                scoped.job_date,
                scoped.retention_days,
                scoped.expires_at,
                scoped.total_files,
                scoped.total_size_bytes,
                scoped.verify_result,
                scoped.source_system,
                scoped.effective_expiry,
                ARRAY_REMOVE(ARRAY_AGG(t.barcode ORDER BY jt.sequence), NULL) AS tape_barcodes
            FROM scoped
            LEFT JOIN backup_job_tape AS jt ON jt.job_id = scoped.id
            LEFT JOIN backup_tape_cartridge AS t ON t.id = jt.tape_id
            WHERE scoped.effective_expiry IS NOT NULL
              AND {where_clause}
            GROUP BY
                scoped.id,
                scoped.name,
                scoped.job_date,
                scoped.retention_days,
                scoped.expires_at,
                scoped.total_files,
                scoped.total_size_bytes,
                scoped.verify_result,
                scoped.source_system,
                scoped.effective_expiry
            ORDER BY scoped.effective_expiry ASC, scoped.id ASC
            LIMIT :limit
            """,
            params,
            )
        except ProgrammingError as exc:
            message = str(exc.orig).lower() if hasattr(exc, "orig") else str(exc).lower()
            if "backup_job" in message:
                raise ToolExecutionError(
                    "Backup job tables are not available. Ensure the backup monitor migrations have been applied."
                ) from exc
            raise

        results: List[Dict[str, Any]] = []
        today = date.today()
        for row in rows:
            expiry_value = row.get("effective_expiry")
            if not isinstance(expiry_value, datetime):
                continue
            expires_at = expiry_value.isoformat()
            days_until = (expiry_value.date() - today).days
            if days_until < 0:
                # Skip already expired jobs that were captured due to clock drift.
                continue
            job_date_value = row.get("job_date")
            if isinstance(job_date_value, datetime):
                job_date_str = job_date_value.isoformat()
            else:
                job_date_str = None
            tape_barcodes = row.get("tape_barcodes") or []
            results.append(
                {
                    "job_id": row["id"],
                    "name": row["name"],
                    "job_date": job_date_str,
                    "retention_days": row.get("retention_days"),
                    "expires_at": expires_at,
                    "days_until_expiry": days_until,
                    "total_files": row.get("total_files"),
                    "total_size_bytes": row.get("total_size_bytes"),
                    "verify_result": row.get("verify_result"),
                    "source_system": row.get("source_system"),
                    "tape_barcodes": list(tape_barcodes),
                }
            )

        return {
            "window_days": arguments.window_days,
            "rows": results,
        }


__all__ = [
    "BackupTapeSummaryTool",
    "BackupJobsExpiringTool",
]
