# api/routes/classification.py
# Classification audit log — server-driven grid for the Logs tab.

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from agent import db
from api.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])

SORTABLE = {
    "id", "business_name", "decision", "assigned_tier",
    "place_id", "created_at",
}


@router.get("")
async def list_log(
    job_id: Optional[str] = None,
    decision: List[str] = Query(default_factory=list),
    tier: List[str] = Query(default_factory=list),
    search: Optional[str] = None,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    sort_col = sort_by if sort_by in SORTABLE else "created_at"
    return db.list_classification_log(
        job_id=job_id,
        decision=decision or None,
        tier=tier or None,
        search=search,
        sort_by=sort_col,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
    )


@router.get("/facets")
async def facets(job_id: Optional[str] = None):
    return db.classification_facets(job_id)


@router.get("/stats")
async def stats(job_id: Optional[str] = None):
    return db.classification_stats(job_id)


@router.get("/{log_id}")
async def get_log(log_id: int):
    row = db.get_classification_log(log_id)
    if not row:
        raise HTTPException(status_code=404, detail="Log entry not found")
    return row
