# -*- coding: utf-8 -*-
"""
Generic, safe table access tools for the MCP server.

Exposes:
- table_fetch:    fetch rows from any public table with column selection, filters, sorting, pagination
- table_get:      fetch a single row by primary key (or unique column)
- table_search:   keyword search over all text-like columns of a table (ILIKE)
Now supports optional `computed` templates to synthesize link/HTML fields.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Tuple
import os
import re
from urllib.parse import quote

from pydantic import BaseModel, Field, field_validator

from ..config import get_settings
from ..db import fetch_all, fetch_one
from .base import BaseTool, ToolExecutionError


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
    )


def _is_ident(name: str) -> bool:
    import re
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""))


async def _list_tables() -> List[str]:
    rows = await fetch_all(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type='BASE TABLE'
        ORDER BY table_name
        """
    )
    return [r["table_name"] for r in rows]


async def _table_columns(table: str) -> List[Dict[str, Any]]:
    rows = await fetch_all(
        """
        SELECT
            c.column_name,
            c.data_type,
            c.is_nullable = 'YES' AS is_nullable,
            c.ordinal_position,
            c.column_default
        FROM information_schema.columns c
        WHERE c.table_schema='public' AND c.table_name = :t
        ORDER BY c.ordinal_position
        """,
        {"t": table},
    )
    return [dict(r) for r in rows]


async def _pk_column(table: str) -> Optional[str]:
    rows = await fetch_all(
        """
        SELECT a.attname AS pk
        FROM   pg_index i
        JOIN   pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE  i.indrelid = (:t)::regclass
        AND    i.indisprimary = true
        """,
        {"t": f'public."{table}"'},
    )
    return rows[0]["pk"] if rows else None


def _normalise_filter(table: str, column: str, value: Any) -> Tuple[str, Any]:
    column_lower = column.lower()
    if table == "knowledge_article" and column_lower in {"status", "is_published"}:
        norm_value = value
        if isinstance(norm_value, str):
            val = norm_value.strip().lower()
            if val in {"published", "true", "yes", "1"}:
                norm_value = True
            elif val in {"draft", "false", "no", "0"}:
                norm_value = False
        return "is_published", norm_value
    if table == "knowledge_attachment" and column_lower in {"knowledge_article_id", "article"}:
        return "article_id", value
    return column, value


def _coerce_date_literal(column: str, value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        raw = value.strip()
        try:
            return date.fromisoformat(raw)
        except ValueError:
            try:
                return datetime.fromisoformat(raw).date()
            except ValueError as exc:
                raise ToolExecutionError(f"Invalid date literal for {column!r}: {value!r}") from exc
    raise ToolExecutionError(f"Expected a date value for {column!r}, got {type(value).__name__}")


def _coerce_boolean_literal(column: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        val = value.strip().lower()
        if val in {"true", "t", "yes", "y", "1"}:
            return True
        if val in {"false", "f", "no", "n", "0"}:
            return False
    raise ToolExecutionError(f"Invalid boolean literal for {column!r}: {value!r}")


def _coerce_integer_literal(column: str, value: Any) -> int:
    if isinstance(value, bool):
        raise ToolExecutionError(f"Invalid integer literal for {column!r}: {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"[+-]?\d+", text):
            try:
                return int(text, 10)
            except ValueError as exc:  # pragma: no cover
                raise ToolExecutionError(f"Invalid integer literal for {column!r}: {value!r}") from exc
    raise ToolExecutionError(f"Invalid integer literal for {column!r}: {value!r}")


def _coerce_timestamp_literal(column: str, value: Any) -> Tuple[datetime, bool]:
    """Return (datetime_value, matched_date_only)."""

    if isinstance(value, datetime):
        return value, False
    if isinstance(value, date):
        dt = datetime.combine(value, time.min)
        return dt, True
    if isinstance(value, str):
        raw = value.strip()
        date_only = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw))
        normalised = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        try:
            parsed = datetime.fromisoformat(normalised)
        except ValueError as exc:
            raise ToolExecutionError(f"Invalid timestamp literal for {column!r}: {value!r}") from exc
        return parsed, date_only
    raise ToolExecutionError(f"Expected a datetime value for {column!r}, got {type(value).__name__}")


def _handle_integer_reference(
    table: str,
    column: str,
    value: str,
    base_param: str,
) -> Optional[Tuple[str, Dict[str, Any]]]:
    """
    Allow natural string inputs for integer foreign keys where it makes sense,
    e.g. ticket.assigned_to='geozac' should match the username.
    """

    lowered = value.strip()
    if not lowered:
        return None

    if table == "ticket" and column in {"assigned_to", "created_by"}:
        param = f"{base_param}_username"
        clause = (
            f'"{column}" IN (SELECT id FROM "user" WHERE LOWER(username) = LOWER(:{param}))'
        )
        return clause, {param: lowered}

    return None


def _prepare_filter_clause(
    table: str,
    column: str,
    value: Any,
    column_meta: Optional[Dict[str, Any]],
) -> Tuple[str, Dict[str, Any]]:
    """Build the SQL clause and params for a single filter."""

    if value is None:
        return f'"{column}" IS NULL', {}

    meta_type = (column_meta or {}).get("data_type")
    base_param = f"p_{column}"

    if meta_type == "boolean":
        coerced = _coerce_boolean_literal(column, value)
        return f'"{column}" = :{base_param}', {base_param: coerced}

    if meta_type == "date":
        coerced = _coerce_date_literal(column, value)
        return f'"{column}" = :{base_param}', {base_param: coerced}

    if meta_type in {"timestamp without time zone", "timestamp with time zone"}:
        coerced, date_only = _coerce_timestamp_literal(column, value)
        if date_only:
            start = coerced
            end = start + timedelta(days=1)
            return (
                f'("{column}" >= :{base_param}_start AND "{column}" < :{base_param}_end)',
                {f"{base_param}_start": start, f"{base_param}_end": end},
            )
        return f'"{column}" = :{base_param}', {base_param: coerced}

    if meta_type in {"integer", "bigint", "smallint"}:
        if isinstance(value, str):
            text = value.strip()
            if text and not re.fullmatch(r"[+-]?\d+", text):
                handled = _handle_integer_reference(table, column, text, base_param)
                if handled:
                    clause, clause_params = handled
                    return clause, clause_params
                raise ToolExecutionError(f"Invalid integer literal for {column!r}: {value!r}")
        coerced = _coerce_integer_literal(column, value)
        return f'"{column}" = :{base_param}', {base_param: coerced}

    return f'"{column}" = :{base_param}', {base_param: value}


def _build_where_and_params(table: str, filters: Dict[str, Any], cols: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    clauses: List[str] = []
    params: Dict[str, Any] = {}
    allowed_cols = [c["column_name"] for c in cols]
    column_meta = {c["column_name"]: c for c in cols}
    for k, v in (filters or {}).items():
        column, value = _normalise_filter(table, k, v)
        if not _is_ident(column) or column not in allowed_cols:
            raise ToolExecutionError(f"Invalid filter column: {column}")
        try:
            clause, clause_params = _prepare_filter_clause(table, column, value, column_meta.get(column))
        except ToolExecutionError:
            raise
        except Exception as exc:  # pragma: no cover
            raise ToolExecutionError(f"Failed to normalise value for {column!r}") from exc
        clauses.append(clause)
        params.update(clause_params)
    where_clause = " AND ".join(clauses) if clauses else "1=1"
    return where_clause, params


def _build_search(search: str, cols: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    text_types = {"text", "character varying", "citext", "varchar"}
    text_cols = [c["column_name"] for c in cols if c["data_type"] in text_types]
    if not text_cols:
        return "1=1", {}
    ors = [f'"{c}" ILIKE :q' for c in text_cols]
    return "(" + " OR ".join(ors) + ")", {"q": f"%{search}%"}


class TableFetchArgs(BaseModel):
    table: str = Field(..., description="Public table name")
    columns: Optional[List[str]] = Field(default=None, description="Optional list of columns to return")
    filters: Optional[Dict[str, Any]] = Field(default=None, description="Exact-match filters per column")
    search: Optional[str] = Field(default=None, description="Keyword to search across text columns (ILIKE)")
    order_by: Optional[List[str]] = Field(default=None, description='Ordering like ["col ASC", "col2 DESC"]')
    limit: int = Field(default=100, ge=1, le=5000)
    offset: int = Field(default=0, ge=0)
    computed: Optional[Dict[str, str]] = Field(
        default=None,
        description=(
            "Optional mapping of new_field -> template that can use row columns and BASE_URL, "
            "e.g. {'download_url': '{BASE_URL}/knowledge/attachments/{filename}', "
            "'html_link': '<a href=\"{BASE_URL}/knowledge/article/{id}\" target=\"_blank\" rel=\"noopener\">{title}</a>'}"
        ),
    )

    @field_validator("table")
    @classmethod
    def _v_table(cls, v: str) -> str:
        if not _is_ident(v):
            raise ValueError("Invalid table identifier")
        return v

    @field_validator("columns")
    @classmethod
    def _v_cols(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v:
            for c in v:
                if not _is_ident(c):
                    raise ValueError(f"Invalid column identifier: {c}")
        return v

    @field_validator("order_by")
    @classmethod
    def _v_order(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if not v:
            return v
        import re
        for part in v:
            m = re.fullmatch(r'([A-Za-z_][A-Za-z0-9_]*)(?:\s+(ASC|DESC))?', part.strip())
            if not m:
                raise ValueError(f"Invalid order_by item: {part}")
        return v


class TableFetchResult(BaseModel):
    table: str
    total: int
    count: int
    limit: int
    offset: int
    columns: List[str]
    rows: List[Dict[str, Any]]


def _apply_computed(rows: List[Dict[str, Any]], computed: Optional[Dict[str, str]]) -> List[Dict[str, Any]]:
    if not computed:
        return rows
    base_url = (getattr(get_settings(), "base_url", None) or os.getenv("BASE_URL", "http://127.0.0.1:5000")).rstrip("/")
    out: List[Dict[str, Any]] = []
    for r in rows:
        r2 = dict(r)
        ctx = {k: ("" if v is None else v) for k, v in r2.items()}
        ctx["BASE_URL"] = base_url
        for key, tmpl in computed.items():
            try:
                value = str(tmpl).format(**ctx)
            except Exception:
                value = str(tmpl)
            r2[key] = value
        out.append(r2)
    return out


def _inject_default_links(table: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not rows:
        return rows
    base_url = (getattr(get_settings(), "base_url", None) or os.getenv("BASE_URL", "http://127.0.0.1:5000")).rstrip("/")
    if table == "knowledge_article":
        for row in rows:
            article_id = row.get("id") or row.get("article_id")
            if not article_id:
                continue
            url = f"{base_url}/knowledge/article/{article_id}"
            title = row.get("title") or f"Article {article_id}"
            row.setdefault("article_url", url)
            row.setdefault(
                "article_link",
                f'<a href="{url}" target="_blank" rel="noopener">{_html_escape(title)}</a>',
            )
            safe_title = title.replace("[", "\\[").replace("]", "\\]")
            row.setdefault("article_markdown_link", f"[{safe_title}]({url})")
    elif table == "knowledge_attachment":
        for row in rows:
            stored = row.get("stored_filename") or row.get("filename") or row.get("original_filename")
            if stored:
                safe_name = quote(str(stored), safe="")
                url = f"{base_url}/knowledge/attachments/{safe_name}"
                link_text = row.get("original_filename") or row.get("filename") or str(stored)
                escaped = _html_escape(link_text)
                markdown_label = link_text.replace("[", "\\[").replace("]", "\\]")
                row.setdefault("download_url", url)
                row.setdefault(
                    "download_link",
                    f'<a href="{url}" target="_blank" rel="noopener">{escaped}</a>',
                )
                row.setdefault("download_markdown", f"[{markdown_label}]({url})")
            article_id = row.get("article_id")
            if article_id:
                article_url = f"{base_url}/knowledge/article/{article_id}"
                row.setdefault("article_url", article_url)
                row.setdefault(
                    "article_link",
                    f'<a href="{article_url}" target="_blank" rel="noopener">Article {article_id}</a>',
                )
                row.setdefault("article_markdown_link", f"[Article {article_id}]({article_url})")
    return rows


class TableFetchTool(BaseTool[TableFetchArgs, TableFetchResult]):
    name = "table_fetch"
    description = "Fetch rows from any public table with filters, keyword search, sorting and pagination."
    input_model = TableFetchArgs
    output_model = TableFetchResult

    async def _run(self, arguments: TableFetchArgs) -> Dict[str, Any]:
        tables = await _list_tables()
        if arguments.table not in tables:
            raise ToolExecutionError(f"Unknown or non-public table: {arguments.table}")

        cols = await _table_columns(arguments.table)
        col_names = [c["column_name"] for c in cols]

        if arguments.columns:
            bad = [c for c in arguments.columns if c not in col_names]
            if bad:
                raise ToolExecutionError(f"Unknown columns for {arguments.table}: {', '.join(bad)}")
            select_list = ", ".join(f'"{c}"' for c in arguments.columns)
            out_cols = arguments.columns
        else:
            select_list = ", ".join(f'"{c}"' for c in col_names)
            out_cols = col_names

        where_filters, params = _build_where_and_params(arguments.table, arguments.filters or {}, cols)

        if arguments.search:
            search_clause, search_params = _build_search(arguments.search, cols)
            where_clause = f"{where_filters} AND {search_clause}"
            params.update(search_params)
        else:
            where_clause = where_filters

        order_sql = ""
        if arguments.order_by:
            order_exprs: List[str] = []
            for part in arguments.order_by:
                tokens = part.split()
                col = tokens[0]
                direction = tokens[1].upper() if len(tokens) > 1 else "ASC"
                if col not in col_names:
                    raise ToolExecutionError(f"Unknown order column: {col}")
                if direction not in ("ASC", "DESC"):
                    raise ToolExecutionError(f"Invalid order direction: {direction}")
                order_exprs.append(f'"{col}" {direction}')
            order_sql = " ORDER BY " + ", ".join(order_exprs)

        total_row = await fetch_one(
            f'SELECT COUNT(*) AS n FROM "{arguments.table}" WHERE {where_clause}',
            params,
        )
        total = int(total_row["n"] if total_row and "n" in total_row else 0)

        rows = await fetch_all(
            f'''
            SELECT {select_list}
            FROM "{arguments.table}"
            WHERE {where_clause}
            {order_sql}
            LIMIT :_limit OFFSET :_offset
            ''',
            {**params, "_limit": arguments.limit, "_offset": arguments.offset},
        )
        row_dicts = [dict(r) for r in rows]
        enriched_rows = _inject_default_links(arguments.table, row_dicts)
        final_rows = _apply_computed(enriched_rows, arguments.computed)

        return {
            "table": arguments.table,
            "total": total,
            "count": len(rows),
            "limit": arguments.limit,
            "offset": arguments.offset,
            "columns": out_cols,
            "rows": final_rows,
        }


class TableGetArgs(BaseModel):
    table: str = Field(..., description="Public table name")
    key_column: Optional[str] = Field(default=None, description="Primary key or unique column; defaults to PK")
    key_value: Any = Field(..., description="Value to match")

    @field_validator("table")
    @classmethod
    def _v_table(cls, v: str) -> str:
        if not _is_ident(v):
            raise ValueError("Invalid table identifier")
        return v

    @field_validator("key_column")
    @classmethod
    def _v_col(cls, v: Optional[str]) -> Optional[str]:
        if v and not _is_ident(v):
            raise ValueError("Invalid column identifier")
        return v


class TableGetResult(BaseModel):
    table: str
    key_column: str
    row: Optional[Dict[str, Any]]


class TableGetTool(BaseTool[TableGetArgs, TableGetResult]):
    name = "table_get"
    description = "Fetch exactly one row from a public table by primary key or a specified unique column."
    input_model = TableGetArgs
    output_model = TableGetResult

    async def _run(self, arguments: TableGetArgs) -> Dict[str, Any]:
        tables = await _list_tables()
        if arguments.table not in tables:
            raise ToolExecutionError(f"Unknown or non-public table: {arguments.table}")

        if arguments.key_column:
            key_col = arguments.key_column
        else:
            key_col = await _pk_column(arguments.table)
            if not key_col:
                raise ToolExecutionError(f"No primary key found for table {arguments.table}; provide key_column")

        cols = await _table_columns(arguments.table)
        col_names = [c["column_name"] for c in cols]
        if key_col not in col_names:
            raise ToolExecutionError(f"Unknown key column: {key_col}")

        row = await fetch_one(
            f'SELECT * FROM "{arguments.table}" WHERE "{key_col}" = :v LIMIT 1',
            {"v": arguments.key_value},
        )
        row_dict = dict(row) if row else None
        if row_dict:
            enriched = _inject_default_links(arguments.table, [row_dict])
            row_dict = enriched[0] if enriched else row_dict
        return {"table": arguments.table, "key_column": key_col, "row": row_dict}


class TableSearchArgs(BaseModel):
    table: str = Field(..., description="Public table name")
    q: str = Field(..., description="Keyword for ILIKE search across text-ish columns")
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)

    @field_validator("table")
    @classmethod
    def _v_table(cls, v: str) -> str:
        if not _is_ident(v):
            raise ValueError("Invalid table identifier")
        return v


class TableSearchResult(BaseModel):
    table: str
    total: int
    count: int
    limit: int
    offset: int
    columns: List[str]
    rows: List[Dict[str, Any]]


class TableSearchTool(BaseTool[TableSearchArgs, TableSearchResult]):
    name = "table_search"
    description = "Keyword search (ILIKE) across all text columns of a public table, with pagination."
    input_model = TableSearchArgs
    output_model = TableSearchResult

    async def _run(self, arguments: TableSearchArgs) -> Dict[str, Any]:
        tables = await _list_tables()
        if arguments.table not in tables:
            raise ToolExecutionError(f"Unknown or non-public table: {arguments.table}")

        cols = await _table_columns(arguments.table)
        search_clause, params = _build_search(arguments.q, cols)
        col_names = [c["column_name"] for c in cols]
        select_list = ", ".join(f'"{c}"' for c in col_names)

        total_row = await fetch_one(
            f'SELECT COUNT(*) AS n FROM "{arguments.table}" WHERE {search_clause}',
            params,
        )
        total = int(total_row["n"] if total_row and "n" in total_row else 0)

        rows = await fetch_all(
            f'''
            SELECT {select_list}
            FROM "{arguments.table}"
            WHERE {search_clause}
            ORDER BY 1
            LIMIT :_limit OFFSET :_offset
            ''',
            {**params, "_limit": arguments.limit, "_offset": arguments.offset},
        )
        row_dicts = [dict(r) for r in rows]
        enriched_rows = _inject_default_links(arguments.table, row_dicts)

        return {
            "table": arguments.table,
            "total": total,
            "count": len(rows),
            "limit": arguments.limit,
            "offset": arguments.offset,
            "columns": col_names,
            "rows": enriched_rows,
        }


__all__ = [
    "TableFetchTool",
    "TableGetTool",
    "TableSearchTool",
]
