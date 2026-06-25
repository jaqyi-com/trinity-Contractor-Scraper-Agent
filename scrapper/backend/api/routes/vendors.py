# api/routes/vendors.py
# Vendors browse — distributor results, kept in a SEPARATE tab/section from
# contractors (client request). Mirrors the contractors grid (filters, sort,
# pagination, facets, export) but reads the `vendors` tab.

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from agent import db
from api.auth import get_current_user
# Reuse the contractors grid's filter set + export helpers (same row shape).
from api.routes.contractors import (
    ContractorFilters, SORTABLE, EXPORT_FORMATS, _export_csv, _export_xlsx,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("")
async def list_vendors(
    filters: ContractorFilters = Depends(),
    sort_by: str = "id",
    sort_dir: str = "desc",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    sort_col = sort_by if sort_by in SORTABLE else "id"
    return db.list_vendors(
        filters=filters.to_dict(), sort_by=sort_col, sort_dir=sort_dir,
        limit=limit, offset=offset,
    )


@router.get("/export")
async def export_vendors(
    filters: ContractorFilters = Depends(),
    sort_by: str = "id",
    sort_dir: str = "desc",
    format: str = Query("csv", description="csv | xlsx"),
    include_excluded: bool = Query(False, description="include lumber/out-of-territory rows (audit)"),
):
    """Download the vendor deliverable (drops lumber/out-of-territory by default)."""
    fmt = (format or "csv").lower()
    if fmt not in EXPORT_FORMATS:
        raise HTTPException(status_code=422, detail=f"format must be one of {sorted(EXPORT_FORMATS)}")
    sort_col = sort_by if sort_by in SORTABLE else "id"
    fd = filters.to_dict()
    fd["include_excluded"] = include_excluded
    fd["include_out_of_territory"] = include_excluded
    rows_iter = lambda: db.iter_vendors_filtered(filters=fd, sort_by=sort_col, sort_dir=sort_dir)
    return _export_xlsx(rows_iter) if fmt == "xlsx" else _export_csv(rows_iter)


@router.get("/facets")
async def facets(job_id: Optional[str] = None):
    return db.vendor_facets(job_id)


@router.get("/{vendor_id}")
async def get_vendor(vendor_id: int):
    v = db.get_vendor(vendor_id)
    if not v:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return v
