# -*- coding: utf-8 -*-
"""
Knowledge base MCP tools – with HTML links.

Adds `url`, `html_link`, and `markdown_link` fields for articles, plus
`attachments` enriched with `download_url`, `download_link`, and
`download_markdown` for each attachment row.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
import os
from urllib.parse import quote
from pydantic import BaseModel, Field

from ..config import get_settings
from ..db import fetch_all
from .base import BaseTool


def _base() -> str:
    settings = get_settings()
    base_url = getattr(settings, "base_url", None)
    if not base_url:
        base_url = os.getenv("BASE_URL")
    if not base_url:
        base_url = os.getenv("MCP_BASE_URL")
    if not base_url:
        host = getattr(settings, "app_host", "127.0.0.1")
        port = getattr(settings, "app_port", 8081)
        base_url = f"http://{host}:{port}"
    return base_url.rstrip("/")

def _article_url(article_id: int) -> str:
    return f"{_base()}/knowledge/article/{article_id}"

def _attachment_url(att_name: str | int) -> str:
    """
    Your app serves attachments as: /knowledge/attachments/<filename>
    If filename is missing, fall back to id (still under the same route).
    """
    safe_name = quote(str(att_name), safe="")
    return f"{_base()}/knowledge/attachments/{safe_name}"

def _html_link(text: str, url: str) -> str:
    safe_text = text.replace('"', '&quot;') if text else "link"
    return f'<a href="{url}" target="_blank" rel="noopener">{safe_text}</a>'

def _markdown_link(text: str, url: str) -> str:
    label = (text or "link").replace("[", "\\[").replace("]", "\\]")
    return f"[{label}]({url})"

def _iso(dt: Optional[datetime]) -> Optional[str]:
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).isoformat()
    return dt.astimezone(timezone.utc).isoformat()


# ---------------- Recent Articles ---------------- #

class KnowledgeRecentArticlesArgs(BaseModel):
    limit: int = Field(default=25, ge=1, le=200)
    category: Optional[str] = Field(default=None, description="Filter by category (exact match)")
    tag_contains: Optional[str] = Field(default=None, description="Filter by tag substring if 'tags' column exists")
    include_unpublished: bool = Field(default=False)

class KnowledgeAttachmentRow(BaseModel):
    id: int
    filename: Optional[str] = None
    stored_filename: Optional[str] = None
    file_size: Optional[int] = None
    article_id: Optional[int] = None
    download_url: str
    download_link: str
    download_markdown: str
    article_url: Optional[str] = None
    article_link: Optional[str] = None
    article_markdown: Optional[str] = None

class KnowledgeArticleRow(BaseModel):
    id: int
    title: Optional[str] = None
    category: Optional[str] = None
    is_published: Optional[bool] = None
    updated_at: Optional[str] = None
    url: str
    html_link: str
    markdown_link: str
    attachments: List[KnowledgeAttachmentRow] = Field(default_factory=list)

class KnowledgeRecentArticlesResult(BaseModel):
    total: int
    count: int
    rows: List[KnowledgeArticleRow]


class KnowledgeRecentArticlesTool(BaseTool[KnowledgeRecentArticlesArgs, KnowledgeRecentArticlesResult]):
    name = "knowledge_recent_articles"
    description = "List recently updated knowledge base articles (with HTML links), optionally filtered by category or tag."
    input_model = KnowledgeRecentArticlesArgs
    output_model = KnowledgeRecentArticlesResult

    async def _run(self, arguments: KnowledgeRecentArticlesArgs) -> Dict[str, Any]:
        conditions = ["1=1"]
        params: Dict[str, Any] = {"limit": arguments.limit}

        if not arguments.include_unpublished:
            conditions.append("ka.is_published = TRUE")

        if arguments.category:
            conditions.append("COALESCE(NULLIF(TRIM(ka.category), ''), 'Uncategorised') = :cat")
            params["cat"] = arguments.category

        # Tag filter only if column exists; detect via information_schema
        tag_filter_clause = ""
        tag_cols = await fetch_all(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='public' AND table_name='knowledge_article' AND column_name='tags'
            """
        )
        if arguments.tag_contains and tag_cols:
            tag_filter_clause = " AND ka.tags ILIKE :tag_filter"
            params["tag_filter"] = f"%{arguments.tag_contains}%"

        where_clause = " AND ".join(conditions)
        rows = await fetch_all(
            f"""
            SELECT ka.id, ka.title, ka.category, ka.is_published, ka.updated_at
            FROM knowledge_article AS ka
            WHERE {where_clause}{tag_filter_clause}
            ORDER BY ka.updated_at DESC NULLS LAST, ka.id DESC
            LIMIT :limit
            """,
            params,
        )

        article_ids = [r["id"] for r in rows]
        attachments_map: Dict[int, List[Dict[str, Any]]] = {aid: [] for aid in article_ids}
        if article_ids:
            att_rows = await fetch_all(
                """
                SELECT a.id, a.article_id, a.original_filename, a.stored_filename, a.file_size
                FROM knowledge_attachment a
                WHERE a.article_id = ANY(:ids)
                ORDER BY a.id ASC
                """,
                {"ids": article_ids},
            )
            for a in att_rows:
                article_id = a["article_id"]
                filename = a.get("original_filename")
                stored_name = a.get("stored_filename")
                url_key = stored_name or filename or a["id"]
                url = _attachment_url(url_key)
                link_text = filename or f"attachment {a['id']}"
                size_val = a.get("file_size")
                try:
                    size = int(size_val) if size_val is not None else None
                except (TypeError, ValueError):
                    size = None
                # ensure markdown and html variants are available to the assistant
                article_url = _article_url(article_id) if article_id else None
                attachments_map.setdefault(article_id, []).append({
                    "id": int(a["id"]),
                    "filename": filename,
                    "stored_filename": stored_name,
                    "file_size": size,
                    "article_id": int(article_id) if article_id is not None else None,
                    "article_url": article_url,
                    "article_link": _html_link(f"Article {article_id}", article_url) if article_url else None,
                    "article_markdown": _markdown_link(f"Article {article_id}", article_url) if article_url else None,
                    "download_url": url,
                    "download_link": _html_link(link_text, url),
                    "download_markdown": _markdown_link(link_text, url),
                })

        result_rows: List[Dict[str, Any]] = []
        for r in rows:
            aid = int(r["id"])
            url = _article_url(aid)
            result_rows.append({
                "id": aid,
                "title": r.get("title"),
                "category": r.get("category"),
                "is_published": bool(r.get("is_published")) if r.get("is_published") is not None else None,
                "updated_at": _iso(r.get("updated_at")),
                "url": url,
                "html_link": _html_link(r.get("title") or f"Article {aid}", url),
                "markdown_link": _markdown_link(r.get("title") or f"Article {aid}", url),
                "attachments": attachments_map.get(aid, []),
            })

        return {
            "total": len(result_rows),
            "count": len(result_rows),
            "rows": result_rows,
        }


# ---------------- Category Summary ---------------- #

class KnowledgeCategorySummaryArgs(BaseModel):
    tag_contains: Optional[str] = Field(default=None)
    include_unpublished: bool = Field(default=False)
    limit_categories: int = Field(default=100, ge=1, le=500)

class KnowledgeCategorySummaryRow(BaseModel):
    category: str
    total_articles: int
    published_articles: int
    category_url: str
    category_link: str

class KnowledgeCategorySummaryResult(BaseModel):
    count: int
    rows: List[KnowledgeCategorySummaryRow]


class KnowledgeCategorySummaryTool(BaseTool[KnowledgeCategorySummaryArgs, KnowledgeCategorySummaryResult]):
    name = "knowledge_category_summary"
    description = "Summarize article counts per category with HTML links to category pages."
    input_model = KnowledgeCategorySummaryArgs
    output_model = KnowledgeCategorySummaryResult

    async def _run(self, arguments: KnowledgeCategorySummaryArgs) -> Dict[str, Any]:
        conditions = ["1=1"]
        params: Dict[str, Any] = {}

        if not arguments.include_unpublished:
            conditions.append("ka.is_published = TRUE")

        tag_filter_clause = ""
        tag_cols = await fetch_all(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='public' AND table_name='knowledge_article' AND column_name='tags'
            """
        )
        if arguments.tag_contains and tag_cols:
            tag_filter_clause = " AND ka.tags ILIKE :tag_filter"
            params["tag_filter"] = f"%{arguments.tag_contains}%"

        where_clause = " AND ".join(conditions)

        rows = await fetch_all(
            f"""
            SELECT
                COALESCE(NULLIF(TRIM(ka.category), ''), 'Uncategorised') AS category,
                COUNT(*) AS total_articles,
                SUM(CASE WHEN ka.is_published THEN 1 ELSE 0 END) AS published_articles
            FROM knowledge_article AS ka
            WHERE {where_clause}{tag_filter_clause}
            GROUP BY COALESCE(NULLIF(TRIM(ka.category), ''), 'Uncategorised')
            ORDER BY total_articles DESC, category ASC
            LIMIT :lim
            """,
            {**params, "lim": arguments.limit_categories},
        )

        out_rows: List[Dict[str, Any]] = []
        for r in rows:
            cat = r["category"]
            url = f"{_base()}/knowledge?category={cat}"
            out_rows.append({
                "category": cat,
                "total_articles": int(r["total_articles"]),
                "published_articles": int(r["published_articles"] or 0),
                "category_url": url,
                "category_link": _html_link(cat, url),
            })

        return {
            "count": len(out_rows),
            "rows": out_rows,
        }


__all__ = [
    "KnowledgeRecentArticlesTool",
    "KnowledgeCategorySummaryTool",
]
