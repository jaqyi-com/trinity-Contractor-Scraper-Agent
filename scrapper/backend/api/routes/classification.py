# api/routes/classification.py
# Classification audit log — server-driven grid for the Logs tab.

from typing import Optional, List
from fastapi import APIRouter, Query, Depends, HTTPException
from psycopg2.extras import RealDictCursor

from agent.db import _get_conn
from api.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])

SORTABLE = {
    "id", "business_name", "decision", "assigned_tier",
    "place_id", "created_at",
}


@router.get("")
async def list_log(
    job_id: Optional[str] = None,
    decision: List[str] = Query(default_factory=list),    # ['INCLUDED','EXCLUDED']
    tier: List[str] = Query(default_factory=list),        # multi-value
    search: Optional[str] = None,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    sort_col = sort_by if sort_by in SORTABLE else "created_at"
    sort_d = "ASC" if sort_dir.lower() == "asc" else "DESC"

    clauses: List[str] = []
    params: list = []

    if job_id:
        clauses.append("job_id = %s")
        params.append(job_id)
    if decision:
        clauses.append("decision = ANY(%s)")
        params.append(decision)
    if tier:
        clauses.append("assigned_tier = ANY(%s)")
        params.append(tier)
    if search:
        clauses.append("(business_name ILIKE %s OR reason ILIKE %s OR classifier_text ILIKE %s)")
        like = f"%{search}%"
        params.extend([like, like, like])

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    conn = _get_conn()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM classification_log {where}", params)
            total = cur.fetchone()["n"]

            cur.execute(
                f"""
                SELECT * FROM classification_log
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


@router.get("/facets")
async def facets(job_id: Optional[str] = None):
    """Distinct values + counts for filter dropdowns on the Logs tab."""
    job_clause = "WHERE job_id = %s" if job_id else ""
    params: list = [job_id] if job_id else []

    conn = _get_conn()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""SELECT decision AS value, COUNT(*) AS n FROM classification_log
                    {job_clause} GROUP BY decision ORDER BY n DESC""",
                params,
            )
            decisions = [dict(r) for r in cur.fetchall()]

            cur.execute(
                f"""SELECT assigned_tier AS value, COUNT(*) AS n FROM classification_log
                    {job_clause} {'AND' if job_clause else 'WHERE'} assigned_tier IS NOT NULL
                    GROUP BY assigned_tier ORDER BY n DESC""",
                params,
            )
            tiers = [dict(r) for r in cur.fetchall()]

            cur.execute(
                f"SELECT COUNT(*) AS total FROM classification_log {job_clause}",
                params,
            )
            total = cur.fetchone()["total"]

            return {
                "total": total,
                "decisions": decisions,
                "tiers": tiers,
            }
    finally:
        conn.close()


@router.get("/stats")
async def stats(job_id: Optional[str] = None):
    """Aggregates used by the Logs tab summary strip."""
    conn = _get_conn()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            job_clause = "WHERE job_id = %s" if job_id else ""
            params = [job_id] if job_id else []

            cur.execute(
                f"SELECT decision, COUNT(*) AS n FROM classification_log {job_clause} GROUP BY decision",
                params,
            )
            by_decision = {r["decision"]: r["n"] for r in cur.fetchall()}

            cur.execute(
                f"""SELECT assigned_tier, COUNT(*) AS n FROM classification_log
                    {job_clause} GROUP BY assigned_tier ORDER BY n DESC""",
                params,
            )
            by_tier = [dict(r) for r in cur.fetchall()]

            return {"by_decision": by_decision, "by_tier": by_tier}
    finally:
        conn.close()


@router.get("/{log_id}")
async def get_log(log_id: int):
    conn = _get_conn()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM classification_log WHERE id = %s", (log_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Log entry not found")
            return dict(row)
    finally:
        conn.close()
