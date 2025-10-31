"""
Schema discovery tools.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict, validator

from ..db import fetch_all
from .base import BaseTool


class ListTablesArgs(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_name: str = Field(
        default="public",
        alias="schema",
        serialization_alias="schema",
        description="Database schema name.",
    )


class ListTablesResult(BaseModel):
    tables: List[str]


class ListTablesTool(BaseTool[ListTablesArgs, ListTablesResult]):
    name = "list_tables"
    description = "List tables available in a given database schema."
    input_model = ListTablesArgs
    output_model = ListTablesResult

    async def _run(self, arguments: ListTablesArgs) -> Dict[str, Any]:
        rows = await fetch_all(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = :schema
              AND table_type = 'BASE TABLE'
            ORDER BY table_name ASC
            """,
            {"schema": arguments.schema_name},
        )
        return {"tables": [row["table_name"] for row in rows]}


class DescribeTableArgs(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    table: str = Field(..., description="Table name to describe.")
    schema_name: str = Field(
        default="public",
        alias="schema",
        serialization_alias="schema",
        description="Database schema name.",
    )

    @validator("table")
    def validate_table(cls, value: str) -> str:
        if not value:
            raise ValueError("table name must not be empty")
        return value


class TableColumn(BaseModel):
    name: str
    data_type: str
    is_nullable: bool
    default: Optional[str] = None


class DescribeTableResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    table: str
    schema_name: str = Field(
        alias="schema",
        serialization_alias="schema",
    )
    columns: List[TableColumn]


class DescribeTableTool(BaseTool[DescribeTableArgs, DescribeTableResult]):
    name = "describe_table"
    description = "Describe columns for a specific table."
    input_model = DescribeTableArgs
    output_model = DescribeTableResult

    async def _run(self, arguments: DescribeTableArgs) -> Dict[str, Any]:
        rows = await fetch_all(
            """
            SELECT
                column_name,
                data_type,
                is_nullable = 'YES' AS is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_schema = :schema
              AND table_name = :table
            ORDER BY ordinal_position ASC
            """,
            {"schema": arguments.schema_name, "table": arguments.table},
        )
        return {
            "table": arguments.table,
            "schema_name": arguments.schema_name,
            "columns": [
                {
                    "name": row["column_name"],
                    "data_type": row["data_type"],
                    "is_nullable": bool(row["is_nullable"]),
                    "default": row["column_default"],
                }
                for row in rows
            ],
        }


__all__ = [
    "ListTablesTool",
    "DescribeTableTool",
]
