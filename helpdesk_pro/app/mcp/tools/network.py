"""
Network inventory MCP tools.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator

from ..db import fetch_all
from .base import BaseTool


def _strip_optional(value: Optional[str]) -> Optional[str]:
    return value.strip() or None if value else None


class NetworkCapacitySummaryArgs(BaseModel):
    site: Optional[str] = Field(
        default=None,
        description="Filter networks by site (case-insensitive).",
    )
    min_capacity: Optional[int] = Field(
        default=None,
        ge=1,
        description="Only include networks whose calculated capacity meets or exceeds this value.",
    )
    limit: int = Field(
        50,
        ge=1,
        le=200,
        description="Maximum number of networks to return.",
    )

    @validator("site")
    def _strip_site_filter(cls, value: Optional[str]) -> Optional[str]:
        return _strip_optional(value)


class NetworkCapacityRow(BaseModel):
    network_id: int
    name: str
    cidr: str
    site: Optional[str]
    vlan: Optional[str]
    capacity: Optional[int]
    assigned_hosts: int
    reserved_hosts: int
    utilisation_percent: Optional[float]


class NetworkCapacitySummaryResult(BaseModel):
    total_networks: int
    total_hosts: int
    total_reserved: int
    rows: List[NetworkCapacityRow]


class NetworkCapacitySummaryTool(BaseTool[NetworkCapacitySummaryArgs, NetworkCapacitySummaryResult]):
    name = "network_capacity_summary"
    description = "Summarise IP network utilisation and capacity."
    input_model = NetworkCapacitySummaryArgs
    output_model = NetworkCapacitySummaryResult

    async def _run(self, arguments: NetworkCapacitySummaryArgs) -> Dict[str, Any]:
        conditions = ["1=1"]
        params: Dict[str, Any] = {"limit": arguments.limit}

        if arguments.site:
            conditions.append("LOWER(n.site) = LOWER(:site)")
            params["site"] = arguments.site
        where_clause = " AND ".join(conditions)

        capacity_filter = ""
        if arguments.min_capacity is not None:
            capacity_filter = " WHERE base.capacity >= :min_capacity"
            params["min_capacity"] = arguments.min_capacity

        rows = await fetch_all(
            f"""
            WITH base AS (
                SELECT
                    n.id,
                    n.name,
                    n.cidr,
                    n.site,
                    n.vlan,
                    COUNT(nh.id) AS assigned_hosts,
                    SUM(CASE WHEN nh.is_reserved THEN 1 ELSE 0 END) AS reserved_hosts,
                    CASE
                        WHEN n.cidr IS NULL THEN NULL
                        WHEN family(n.cidr::inet) = 4 THEN
                            GREATEST(
                                power(2, 32 - masklen(n.cidr::inet))
                                - CASE WHEN masklen(n.cidr::inet) <= 30 THEN 2 ELSE 0 END,
                                0
                            )::numeric
                        WHEN family(n.cidr::inet) = 6 THEN
                            power(2, 128 - masklen(n.cidr::inet))::numeric
                        ELSE NULL
                    END AS capacity
                FROM network AS n
                LEFT JOIN network_host AS nh ON nh.network_id = n.id
                WHERE {where_clause}
                GROUP BY n.id, n.name, n.cidr, n.site, n.vlan
            )
            SELECT
                base.*,
                CASE
                    WHEN capacity IS NULL OR capacity = 0 THEN NULL
                    ELSE ROUND((assigned_hosts::numeric / capacity) * 100, 2)
                END AS utilisation_percent
            FROM base
            {capacity_filter}
            ORDER BY utilisation_percent DESC NULLS LAST, assigned_hosts DESC, id ASC
            LIMIT :limit
            """,
            params,
        )

        totals_params: Dict[str, Any] = {}
        totals_conditions = ["1=1"]
        if arguments.site:
            totals_conditions.append("LOWER(n.site) = LOWER(:site)")
            totals_params["site"] = arguments.site
        totals_where = " AND ".join(totals_conditions)

        totals = await fetch_all(
            f"""
            SELECT
                COUNT(DISTINCT n.id) AS network_count,
                COUNT(nh.id) AS host_count,
                SUM(CASE WHEN nh.is_reserved THEN 1 ELSE 0 END) AS reserved_count
            FROM network AS n
            LEFT JOIN network_host AS nh ON nh.network_id = n.id
            WHERE {totals_where}
            """,
            totals_params,
        )

        total_networks = int(totals[0]["network_count"]) if totals else 0
        total_hosts = int(totals[0]["host_count"]) if totals else 0
        total_reserved = int(totals[0]["reserved_count"] or 0) if totals else 0

        return {
            "total_networks": total_networks,
            "total_hosts": total_hosts,
            "total_reserved": total_reserved,
            "rows": [
                {
                    "network_id": row["id"],
                    "name": row["name"],
                    "cidr": row["cidr"],
                    "site": row.get("site"),
                    "vlan": row.get("vlan"),
                    "capacity": int(row["capacity"]) if row.get("capacity") is not None else None,
                    "assigned_hosts": int(row["assigned_hosts"]),
                    "reserved_hosts": int(row["reserved_hosts"] or 0),
                    "utilisation_percent": float(row["utilisation_percent"]) if row.get("utilisation_percent") is not None else None,
                }
                for row in rows
            ],
        }


class NetworkHostSearchArgs(BaseModel):
    query: Optional[str] = Field(
        default=None,
        description="Substring match applied to IP address, hostname, MAC address, or assigned_to.",
    )
    device_type: Optional[str] = Field(
        default=None,
        description="Filter by device type (case-insensitive).",
    )
    site: Optional[str] = Field(
        default=None,
        description="Filter hosts by parent network site (case-insensitive).",
    )
    reserved_only: bool = Field(
        False,
        description="When true, only return reserved hosts.",
    )
    limit: int = Field(
        50,
        ge=1,
        le=200,
        description="Maximum number of hosts to return.",
    )

    @validator("query", "device_type", "site")
    def _strip_filters(cls, value: Optional[str]) -> Optional[str]:
        return _strip_optional(value)


class NetworkHostRow(BaseModel):
    host_id: int
    network_id: int
    site: Optional[str]
    cidr: str
    ip_address: str
    hostname: Optional[str]
    mac_address: Optional[str]
    device_type: Optional[str]
    assigned_to: Optional[str]
    is_reserved: bool


class NetworkHostSearchResult(BaseModel):
    rows: List[NetworkHostRow]


class NetworkHostSearchTool(BaseTool[NetworkHostSearchArgs, NetworkHostSearchResult]):
    name = "network_host_search"
    description = "Find hosts within networks by IP, hostname, MAC address, or assignment notes."
    input_model = NetworkHostSearchArgs
    output_model = NetworkHostSearchResult

    async def _run(self, arguments: NetworkHostSearchArgs) -> Dict[str, Any]:
        conditions = ["1=1"]
        params: Dict[str, Any] = {"limit": arguments.limit}

        if arguments.device_type:
            conditions.append("LOWER(nh.device_type) = LOWER(:device_type)")
            params["device_type"] = arguments.device_type
        if arguments.site:
            conditions.append("LOWER(n.site) = LOWER(:site)")
            params["site"] = arguments.site
        if arguments.reserved_only:
            conditions.append("COALESCE(nh.is_reserved, FALSE) = TRUE")
        if arguments.query:
            params["query"] = f"%{arguments.query}%"
            conditions.append(
                """
                (
                    nh.ip_address ILIKE :query
                    OR nh.hostname ILIKE :query
                    OR nh.mac_address ILIKE :query
                    OR nh.assigned_to ILIKE :query
                )
                """
            )

        where_clause = " AND ".join(conditions)

        rows = await fetch_all(
            f"""
            SELECT
                nh.id,
                nh.network_id,
                n.site,
                n.cidr,
                nh.ip_address,
                nh.hostname,
                nh.mac_address,
                nh.device_type,
                nh.assigned_to,
                COALESCE(nh.is_reserved, FALSE) AS is_reserved
            FROM network_host AS nh
            JOIN network AS n ON n.id = nh.network_id
            WHERE {where_clause}
            ORDER BY nh.ip_address ASC
            LIMIT :limit
            """,
            params,
        )

        return {
            "rows": [
                {
                    "host_id": row["id"],
                    "network_id": row["network_id"],
                    "site": row.get("site"),
                    "cidr": row["cidr"],
                    "ip_address": row["ip_address"],
                    "hostname": row.get("hostname"),
                    "mac_address": row.get("mac_address"),
                    "device_type": row.get("device_type"),
                    "assigned_to": row.get("assigned_to"),
                    "is_reserved": bool(row.get("is_reserved")),
                }
                for row in rows
            ]
        }


__all__ = [
    "NetworkCapacitySummaryTool",
    "NetworkHostSearchTool",
]
