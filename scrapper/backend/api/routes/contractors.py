# api/routes/contractors.py
# Contractors browse — main "final data" surface for the UI grid.
# Server-driven: filters, sort, pagination, faceted counts.

import csv
import io
from datetime import datetime, date
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse
from psycopg2.extras import RealDictCursor

from agent.db import _get_conn
from api.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])

# Allowlist of columns the client can sort by — prevents SQL injection
# (sort column is interpolated into the SQL string).
SORTABLE = {
    "id", "business_name", "city", "zip_code", "address", "tier", "license_status",
    "phone", "email", "website", "owner_name",
    "google_rating", "google_review_count",
    "bbb_rating", "bbb_accredited", "years_in_business",
    "scraped_at", "job_id",
}


class ContractorFilters:
    """Shared filter set for the contractor grid + CSV export.

    Used as a FastAPI dependency so `list`, `export` (and any future reader)
    accept an identical query-param surface and build the WHERE clause the
    same way. Every grid column maps to a filter here:

      - enum facets (city/tier/license_status): multi-value, matches ANY
      - scalar text:                             ILIKE "contains"
      - JSONB array (keywords/categories/...):   cast to text + ILIKE (any element)
      - presence (phone/email/website):          IS [NOT] NULL / <> ''
      - numeric (rating/reviews/years):          >= minimum
      - bool (bbb_accredited):                   exact
    """

    # Scalar TEXT columns filtered by ILIKE "contains".
    _TEXT_COLS = ("business_name", "zip_code", "address", "owner_name", "bbb_rating")
    # JSONB array columns — cast to text + ILIKE matches any element.
    _JSON_COLS = (
        "specialty_keywords", "google_categories", "services_listed",
        "license_numbers", "license_categories", "sources", "place_ids",
    )

    def __init__(
        self,
        job_id: Optional[str] = None,
        # enum facets (repeated query params)
        city: List[str] = Query(default_factory=list),
        tier: List[str] = Query(default_factory=list),
        license_status: List[str] = Query(default_factory=list),
        # global search across the common contact columns
        search: Optional[str] = None,
        # scalar text "contains"
        business_name: Optional[str] = None,
        zip_code: Optional[str] = None,
        address: Optional[str] = None,
        owner_name: Optional[str] = None,
        bbb_rating: Optional[str] = None,
        # JSONB array "contains"
        specialty_keywords: Optional[str] = None,
        google_categories: Optional[str] = None,
        services_listed: Optional[str] = None,
        license_numbers: Optional[str] = None,
        license_categories: Optional[str] = None,
        sources: Optional[str] = None,
        place_ids: Optional[str] = None,
        # presence toggles
        has_email: Optional[bool] = None,
        has_phone: Optional[bool] = None,
        has_website: Optional[bool] = None,
        bbb_accredited: Optional[bool] = None,
        # numeric minimums
        min_rating: Optional[float] = None,
        min_review_count: Optional[int] = None,
        min_years: Optional[int] = None,
    ):
        self.job_id = job_id
        self.city = city
        self.tier = tier
        self.license_status = license_status
        self.search = search
        self.business_name = business_name
        self.zip_code = zip_code
        self.address = address
        self.owner_name = owner_name
        self.bbb_rating = bbb_rating
        self.specialty_keywords = specialty_keywords
        self.google_categories = google_categories
        self.services_listed = services_listed
        self.license_numbers = license_numbers
        self.license_categories = license_categories
        self.sources = sources
        self.place_ids = place_ids
        self.has_email = has_email
        self.has_phone = has_phone
        self.has_website = has_website
        self.bbb_accredited = bbb_accredited
        self.min_rating = min_rating
        self.min_review_count = min_review_count
        self.min_years = min_years

    def build(self) -> tuple[str, list]:
        """Return ``(where_clause, params)`` for parameterised execution."""
        clauses: List[str] = []
        params: list = []

        if self.job_id:
            clauses.append("job_id = %s"); params.append(self.job_id)
        if self.city:
            clauses.append("city = ANY(%s)"); params.append(self.city)
        if self.tier:
            clauses.append("tier = ANY(%s)"); params.append(self.tier)
        if self.license_status:
            clauses.append("license_status = ANY(%s)"); params.append(self.license_status)
        if self.search:
            clauses.append(
                "(business_name ILIKE %s OR phone ILIKE %s OR email ILIKE %s "
                "OR website ILIKE %s OR address ILIKE %s)"
            )
            like = f"%{self.search}%"
            params.extend([like, like, like, like, like])

        # Scalar text "contains"
        for col in self._TEXT_COLS:
            val = getattr(self, col)
            if val:
                clauses.append(f"{col} ILIKE %s"); params.append(f"%{val}%")

        # JSONB array "contains" — cast the array to text and match any element
        for col in self._JSON_COLS:
            val = getattr(self, col)
            if val:
                clauses.append(f"{col}::text ILIKE %s"); params.append(f"%{val}%")

        # Presence toggles
        if self.has_email is not None:
            clauses.append("email IS NOT NULL AND email <> ''" if self.has_email else "(email IS NULL OR email = '')")
        if self.has_phone is not None:
            clauses.append("phone IS NOT NULL AND phone <> ''" if self.has_phone else "(phone IS NULL OR phone = '')")
        if self.has_website is not None:
            clauses.append("website IS NOT NULL AND website <> ''" if self.has_website else "(website IS NULL OR website = '')")
        if self.bbb_accredited is not None:
            clauses.append("bbb_accredited = %s"); params.append(self.bbb_accredited)

        # Numeric minimums
        if self.min_rating is not None:
            clauses.append("google_rating >= %s"); params.append(self.min_rating)
        if self.min_review_count is not None:
            clauses.append("google_review_count >= %s"); params.append(self.min_review_count)
        if self.min_years is not None:
            clauses.append("years_in_business >= %s"); params.append(self.min_years)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params


@router.get("")
async def list_contractors(
    filters: ContractorFilters = Depends(),
    sort_by: str = "id",
    sort_dir: str = "desc",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """
    Filtered, sorted, paginated contractor list.

    Every column is filterable (see ``ContractorFilters``). Multi-value enum
    filters use repeated query params, e.g.
      ?city=Tampa&city=Orlando&tier=TIER_1_DRYWALL&owner_name=smith&min_years=5
    """
    sort_col = sort_by if sort_by in SORTABLE else "id"
    sort_d = "ASC" if sort_dir.lower() == "asc" else "DESC"

    where, params = filters.build()

    conn = _get_conn()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM contractors {where}", params)
            total = cur.fetchone()["n"]

            cur.execute(
                f"""
                SELECT * FROM contractors
                {where}
                ORDER BY {sort_col} {sort_d} NULLS LAST, id DESC
                LIMIT %s OFFSET %s
                """,
                params + [limit, offset],
            )
            rows = [dict(r) for r in cur.fetchall()]

            return {
                "total": total,
                "limit": limit,
                "offset": offset,
                "rows": rows,
            }
    finally:
        conn.close()


EXPORT_COLUMNS = [
    "id", "business_name", "city", "zip_code", "address",
    "tier", "specialty_keywords", "google_categories", "services_listed",
    "phone", "email", "website", "owner_name",
    "license_status", "license_numbers", "license_categories",
    "google_rating", "google_review_count",
    "bbb_rating", "bbb_accredited", "years_in_business",
    "social_profiles", "sources", "place_ids",
    "scraped_at", "job_id",
]


def _csv_cell(value):
    """Coerce DB values into CSV-safe scalars."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "; ".join("" if v is None else str(v) for v in value)
    if isinstance(value, dict):
        return "; ".join(f"{k}={v}" for k, v in value.items() if v is not None)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


@router.get("/export")
async def export_contractors(
    filters: ContractorFilters = Depends(),
    sort_by: str = "id",
    sort_dir: str = "desc",
):
    """
    Stream the full filtered contractor set as CSV.

    Same filters/sort as `list_contractors`, but no pagination — returns
    every matching row. Uses a server-side cursor so memory stays flat even
    for large exports (Cloud Run / Render safe).
    """
    sort_col = sort_by if sort_by in SORTABLE else "id"
    sort_d = "ASC" if sort_dir.lower() == "asc" else "DESC"

    where, params = filters.build()
    select_cols = ", ".join(EXPORT_COLUMNS)
    sql = (
        f"SELECT {select_cols} FROM contractors {where} "
        f"ORDER BY {sort_col} {sort_d} NULLS LAST, id DESC"
    )

    def row_iter():
        # Server-side named cursor → rows stream from Postgres in batches
        # instead of being buffered in memory. Safe for 100k+ row exports
        # under Cloud Run's stateless model (no disk needed).
        conn = _get_conn()
        try:
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(EXPORT_COLUMNS)
            yield buf.getvalue()
            buf.seek(0); buf.truncate(0)

            with conn.cursor(name="contractor_export") as cur:
                cur.itersize = 1000
                cur.execute(sql, params)
                for row in cur:
                    writer.writerow([_csv_cell(v) for v in row])
                    if buf.tell() > 64 * 1024:
                        yield buf.getvalue()
                        buf.seek(0); buf.truncate(0)
            if buf.tell():
                yield buf.getvalue()
        finally:
            conn.close()

    filename = f"contractors_{date.today().isoformat()}.csv"
    return StreamingResponse(
        row_iter(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # Cloud Run / proxies: don't buffer the stream
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/facets")
async def facets(job_id: Optional[str] = None):
    """Distinct values + counts for filter dropdowns."""
    job_clause = "WHERE job_id = %s" if job_id else ""
    params: list = [job_id] if job_id else []

    conn = _get_conn()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""SELECT city AS value, COUNT(*) AS n FROM contractors
                    {job_clause} {'AND' if job_clause else 'WHERE'} city IS NOT NULL
                    GROUP BY city ORDER BY n DESC""",
                params,
            )
            cities = [dict(r) for r in cur.fetchall()]

            cur.execute(
                f"""SELECT tier AS value, COUNT(*) AS n FROM contractors
                    {job_clause} {'AND' if job_clause else 'WHERE'} tier IS NOT NULL
                    GROUP BY tier ORDER BY n DESC""",
                params,
            )
            tiers = [dict(r) for r in cur.fetchall()]

            cur.execute(
                f"""SELECT license_status AS value, COUNT(*) AS n FROM contractors
                    {job_clause} {'AND' if job_clause else 'WHERE'} license_status IS NOT NULL
                    GROUP BY license_status ORDER BY n DESC""",
                params,
            )
            statuses = [dict(r) for r in cur.fetchall()]

            cur.execute(
                f"SELECT COUNT(*) AS total FROM contractors {job_clause}",
                params,
            )
            total = cur.fetchone()["total"]

            return {
                "total": total,
                "cities": cities,
                "tiers": tiers,
                "license_statuses": statuses,
            }
    finally:
        conn.close()


@router.get("/{contractor_id}")
async def get_contractor(contractor_id: int):
    conn = _get_conn()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM contractors WHERE id = %s", (contractor_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Contractor not found")
            return dict(row)
    finally:
        conn.close()


@router.get("/{contractor_id}/classification")
async def contractor_classification(contractor_id: int):
    """Audit trail for one contractor — the "why included" details.

    The classifier logs decisions before the contractor row exists, so
    classification_log.contractor_id is never set. We instead link by the
    Google place_id (logged per decision; stored as place_ids on the row),
    falling back to the normalized business name.
    """
    conn = _get_conn()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT business_name, place_ids FROM contractors WHERE id = %s",
                (contractor_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Contractor not found")

            place_ids = row.get("place_ids") or []
            if place_ids:
                cur.execute(
                    """
                    SELECT * FROM classification_log
                    WHERE contractor_id = %s OR place_id = ANY(%s)
                    ORDER BY created_at DESC
                    """,
                    (contractor_id, place_ids),
                )
            else:
                cur.execute(
                    """
                    SELECT * FROM classification_log
                    WHERE contractor_id = %s OR business_name = %s
                    ORDER BY created_at DESC
                    """,
                    (contractor_id, row.get("business_name")),
                )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
