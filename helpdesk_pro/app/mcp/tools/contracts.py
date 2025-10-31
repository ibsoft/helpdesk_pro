"""
Contract-related MCP tools.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator

from ..db import fetch_all
from .base import BaseTool, ToolExecutionError


def _coerce_decimal(value: Any) -> Optional[str]:
    if value is None:
        return None
    return format(value, "f")


class ContractsSummaryArgs(BaseModel):
    status: Optional[List[str]] = Field(
        default=None,
        description="Optional list of contract statuses to filter.",
    )
    vendor: Optional[str] = Field(default=None, description="Filter by vendor name.")
    currency: Optional[str] = Field(default=None, description="Filter by currency code.")

    @validator("status")
    def validate_status(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value:
            cleaned = [item.strip() for item in value if item.strip()]
            if not cleaned:
                return None
            return cleaned
        return None


class ContractsSummaryRow(BaseModel):
    vendor: str
    currency: str
    contract_count: int
    total_value: Optional[str] = None


class ContractsSummaryResult(BaseModel):
    rows: List[ContractsSummaryRow]


class ContractsSummaryTool(BaseTool[ContractsSummaryArgs, ContractsSummaryResult]):
    name = "contracts_summary"
    description = "Summarise total contract value grouped by vendor and currency."
    input_model = ContractsSummaryArgs
    output_model = ContractsSummaryResult

    async def _run(self, arguments: ContractsSummaryArgs) -> Dict[str, Any]:
        conditions = ["1=1"]
        params: Dict[str, Any] = {}

        if arguments.status:
            conditions.append("status = ANY(:status_list)")
            params["status_list"] = arguments.status
        if arguments.vendor:
            conditions.append("vendor ILIKE :vendor")
            params["vendor"] = f"%{arguments.vendor}%"
        if arguments.currency:
            conditions.append("currency = :currency")
            params["currency"] = arguments.currency

        where_clause = " AND ".join(conditions)
        query = f"""
            SELECT
                COALESCE(vendor, 'Unspecified') AS vendor,
                COALESCE(currency, 'Unspecified') AS currency,
                COUNT(*) AS contract_count,
                COALESCE(SUM(value), 0) AS total_value
            FROM contract
            WHERE {where_clause}
            GROUP BY vendor, currency
            ORDER BY total_value DESC, vendor ASC
        """
        rows = await fetch_all(query, params)
        return {
            "rows": [
                {
                    "vendor": row["vendor"],
                    "currency": row["currency"],
                    "contract_count": int(row["contract_count"]),
                    "total_value": _coerce_decimal(row["total_value"]),
                }
                for row in rows
            ]
        }


class ContractsExpiringArgs(BaseModel):
    window_days: int = Field(
        30,
        ge=1,
        le=365,
        description="Number of days ahead to look for expiring contracts.",
    )
    limit: int = Field(
        50,
        ge=1,
        le=500,
        description="Maximum number of records to return.",
    )
    include_auto_renew: bool = Field(
        False, description="Include contracts that auto-renew."
    )
    status: Optional[List[str]] = Field(
        default=None, description="Optional list of statuses to include."
    )

    @validator("status")
    def validate_status(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value:
            cleaned = [item.strip() for item in value if item.strip()]
            if not cleaned:
                return None
            return cleaned
        return None


class ContractsExpiringRow(BaseModel):
    contract_id: int
    name: str
    vendor: Optional[str]
    status: Optional[str]
    end_date: Optional[str]
    renewal_date: Optional[str]
    value: Optional[str]
    currency: Optional[str]
    auto_renew: bool


class ContractsExpiringResult(BaseModel):
    rows: List[ContractsExpiringRow]


class ContractsExpiringTool(BaseTool[ContractsExpiringArgs, ContractsExpiringResult]):
    name = "contracts_expiring"
    description = "List contracts with end dates within an upcoming window."
    input_model = ContractsExpiringArgs
    output_model = ContractsExpiringResult

    async def _run(self, arguments: ContractsExpiringArgs) -> Dict[str, Any]:
        if arguments.window_days <= 0:
            raise ToolExecutionError("window_days must be positive")

        conditions = ["end_date IS NOT NULL"]
        params: Dict[str, Any] = {
            "window_days": arguments.window_days,
            "limit": arguments.limit,
        }

        conditions.append(
            "end_date BETWEEN CURRENT_DATE AND (CURRENT_DATE + (INTERVAL '1 day' * :window_days))"
        )

        if not arguments.include_auto_renew:
            conditions.append("(auto_renew IS NULL OR auto_renew = FALSE)")
        if arguments.status:
            conditions.append("status = ANY(:status_list)")
            params["status_list"] = arguments.status

        where_clause = " AND ".join(conditions)
        query = f"""
            SELECT
                id,
                name,
                vendor,
                status,
                end_date::date AS end_date,
                renewal_date::date AS renewal_date,
                value,
                currency,
                COALESCE(auto_renew, FALSE) AS auto_renew
            FROM contract
            WHERE {where_clause}
            ORDER BY end_date ASC
            LIMIT :limit
        """
        rows = await fetch_all(query, params)
        return {
            "rows": [
                {
                    "contract_id": row["id"],
                    "name": row["name"],
                    "vendor": row["vendor"],
                    "status": row["status"],
                    "end_date": row["end_date"].isoformat() if row["end_date"] else None,
                    "renewal_date": row["renewal_date"].isoformat()
                    if row["renewal_date"]
                    else None,
                    "value": _coerce_decimal(row["value"]),
                    "currency": row["currency"],
                    "auto_renew": bool(row["auto_renew"]),
                }
                for row in rows
            ]
        }


__all__ = [
    "ContractsSummaryTool",
    "ContractsExpiringTool",
]
