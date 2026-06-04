# api/routes/result_sheets.py
# Per-run dynamic result sheets — the UI's "view this run's results" surface.
#   GET /api/result-sheets               → list of runs that have a result sheet
#   GET /api/result-sheets/current       → the latest one (UI default)
#   GET /api/result-sheets/{job_id}/contractors → that run's rows (filter/sort/page)
#
# Reads a dynamic spreadsheet on demand (cached briefly to spare the Sheets API)
# and reuses the exact same filter/sort/pagination as the master contractors grid.

import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from agent import db, dynamic_sheets
from api.auth import get_current_user
from api.routes.contractors import ContractorFilters, SORTABLE

router = APIRouter(dependencies=[Depends(get_current_user)])

# Short-lived cache so polling/paging doesn't hit Sheets on every request.
_CACHE_TTL = 30.0
_cache: dict = {}  # sheet_id -> (monotonic_ts, rows)


def _read_sheet_cached(sheet_id: str):
    now = time.monotonic()
    hit = _cache.get(sheet_id)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    rows = dynamic_sheets.read_run_rows(sheet_id)
    _cache[sheet_id] = (now, rows)
    return rows


@router.get("")
async def list_sheets():
    """All runs with a result sheet (newest first) — for the picker dropdown."""
    return db.list_result_sheets()


@router.get("/current")
async def current_sheet():
    """The most recent run's result sheet (UI's default selection), or null."""
    sheets = db.list_result_sheets()
    return sheets[0] if sheets else None


@router.get("/{job_id}/contractors")
async def sheet_contractors(
    job_id: str,
    filters: ContractorFilters = Depends(),
    sort_by: str = "id",
    sort_dir: str = "desc",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    job = db.get_job(job_id)
    if not job or not job.get("result_sheet_id"):
        raise HTTPException(status_code=404, detail="No result sheet for this job")
    rows = _read_sheet_cached(job["result_sheet_id"])
    sort_col = sort_by if sort_by in SORTABLE else "id"
    return db.filter_sort_paginate(rows, filters.to_dict(), sort_col, sort_dir, limit, offset)
