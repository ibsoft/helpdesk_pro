"""
Address book MCP tools.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator

from ..db import fetch_all
from .base import BaseTool


def _strip_optional(value: Optional[str]) -> Optional[str]:
    return value.strip() or None if value else None


class AddressBookSearchArgs(BaseModel):
    query: Optional[str] = Field(
        default=None,
        description="Search term applied to name, company, email, phone, and tags.",
    )
    category: Optional[str] = Field(
        default=None, description="Filter by contact category (case-insensitive)."
    )
    company: Optional[str] = Field(
        default=None, description="Filter by company name substring."
    )
    limit: int = Field(
        25,
        ge=1,
        le=200,
        description="Maximum number of contacts to return.",
    )

    @validator("query", "category", "company")
    def _strip_fields(cls, value: Optional[str]) -> Optional[str]:
        return _strip_optional(value)


class AddressBookContact(BaseModel):
    contact_id: int
    name: str
    category: Optional[str]
    company: Optional[str]
    job_title: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    mobile: Optional[str]
    tags: Optional[str]
    city: Optional[str]
    country: Optional[str]


class AddressBookSearchResult(BaseModel):
    rows: List[AddressBookContact]


class AddressBookSearchTool(BaseTool[AddressBookSearchArgs, AddressBookSearchResult]):
    name = "address_book_search"
    description = "Search address book entries by name, company, contact details, or tags."
    input_model = AddressBookSearchArgs
    output_model = AddressBookSearchResult

    async def _run(self, arguments: AddressBookSearchArgs) -> Dict[str, Any]:
        conditions = ["1=1"]
        params: Dict[str, Any] = {"limit": arguments.limit}

        if arguments.category:
            conditions.append("LOWER(abe.category) = LOWER(:category)")
            params["category"] = arguments.category
        if arguments.company:
            conditions.append("abe.company ILIKE :company")
            params["company"] = f"%{arguments.company}%"
        if arguments.query:
            params["query"] = f"%{arguments.query}%"
            conditions.append(
                """
                (
                    abe.name ILIKE :query
                    OR abe.company ILIKE :query
                    OR abe.email ILIKE :query
                    OR abe.phone ILIKE :query
                    OR abe.mobile ILIKE :query
                    OR abe.tags ILIKE :query
                )
                """
            )

        where_clause = " AND ".join(conditions)
        rows = await fetch_all(
            f"""
            SELECT
                abe.id,
                abe.name,
                abe.category,
                abe.company,
                abe.job_title,
                abe.email,
                abe.phone,
                abe.mobile,
                abe.tags,
                abe.city,
                abe.country
            FROM address_book_entry AS abe
            WHERE {where_clause}
            ORDER BY abe.name ASC
            LIMIT :limit
            """,
            params,
        )

        return {
            "rows": [
                {
                    "contact_id": row["id"],
                    "name": row["name"],
                    "category": row.get("category"),
                    "company": row.get("company"),
                    "job_title": row.get("job_title"),
                    "email": row.get("email"),
                    "phone": row.get("phone"),
                    "mobile": row.get("mobile"),
                    "tags": row.get("tags"),
                    "city": row.get("city"),
                    "country": row.get("country"),
                }
                for row in rows
            ]
        }


class AddressBookSummaryArgs(BaseModel):
    country: Optional[str] = Field(
        default=None,
        description="Filter summary counts to a specific country (case-insensitive).",
    )

    @validator("country")
    def _strip_country_filter(cls, value: Optional[str]) -> Optional[str]:
        return _strip_optional(value)


class AddressBookCategoryCount(BaseModel):
    category: str
    count: int


class AddressBookEmailDomainCount(BaseModel):
    domain: str
    count: int


class AddressBookSummaryResult(BaseModel):
    category_counts: List[AddressBookCategoryCount]
    top_email_domains: List[AddressBookEmailDomainCount]


class AddressBookSummaryTool(BaseTool[AddressBookSummaryArgs, AddressBookSummaryResult]):
    name = "address_book_summary"
    description = "Summarise address book coverage by category and top email domains."
    input_model = AddressBookSummaryArgs
    output_model = AddressBookSummaryResult

    async def _run(self, arguments: AddressBookSummaryArgs) -> Dict[str, Any]:
        conditions = ["1=1"]
        params: Dict[str, Any] = {}
        if arguments.country:
            conditions.append("LOWER(abe.country) = LOWER(:country)")
            params["country"] = arguments.country
        where_clause = " AND ".join(conditions)

        category_rows = await fetch_all(
            f"""
            SELECT
                COALESCE(NULLIF(TRIM(abe.category), ''), 'Uncategorised') AS category,
                COUNT(*) AS count
            FROM address_book_entry AS abe
            WHERE {where_clause}
            GROUP BY COALESCE(NULLIF(TRIM(abe.category), ''), 'Uncategorised')
            ORDER BY count DESC, category ASC
            """,
            params,
        )

        domain_rows = await fetch_all(
            f"""
            SELECT
                LOWER(split_part(abe.email, '@', 2)) AS domain,
                COUNT(*) AS count
            FROM address_book_entry AS abe
            WHERE {where_clause}
              AND abe.email ILIKE '%@%'
            GROUP BY LOWER(split_part(abe.email, '@', 2))
            ORDER BY count DESC, domain ASC
            LIMIT 10
            """,
            params,
        )

        return {
            "category_counts": [
                {"category": row["category"], "count": int(row["count"])} for row in category_rows
            ],
            "top_email_domains": [
                {"domain": row["domain"], "count": int(row["count"])} for row in domain_rows if row["domain"]
            ],
        }


__all__ = [
    "AddressBookSearchTool",
    "AddressBookSummaryTool",
]
