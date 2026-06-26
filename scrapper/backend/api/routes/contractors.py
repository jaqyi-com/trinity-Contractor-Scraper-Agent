# api/routes/contractors.py
# Contractors browse — main "final data" surface for the UI grid.
# Server-driven: filters, sort, pagination, faceted counts.

import csv
import io
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from agent import db
from api.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])

# Allowlist of columns the client can sort by — prevents arbitrary attribute access.
SORTABLE = {
    "id", "business_name", "city", "zip_code", "address", "tier", "license_status",
    "phone", "email", "website", "owner_name",
    "google_rating", "google_review_count",
    "bbb_rating", "bbb_accredited", "years_in_business",
    "scraped_at", "job_id",
}


class ContractorFilters:
    """Shared filter set for the contractor grid + CSV export.

    Same query-param surface as before (matches the old psycopg2 route).
    `to_dict()` returns the filter dict consumed by agent.db.list_contractors.
    """

    def __init__(
        self,
        job_id: Optional[str] = None,
        city: List[str] = Query(default_factory=list),
        tier: List[str] = Query(default_factory=list),
        license_status: List[str] = Query(default_factory=list),
        search: Optional[str] = None,
        business_name: Optional[str] = None,
        zip_code: Optional[str] = None,
        address: Optional[str] = None,
        owner_name: Optional[str] = None,
        bbb_rating: Optional[str] = None,
        specialty_keywords: Optional[str] = None,
        google_categories: Optional[str] = None,
        services_listed: Optional[str] = None,
        license_numbers: Optional[str] = None,
        license_categories: Optional[str] = None,
        sources: Optional[str] = None,
        place_ids: Optional[str] = None,
        has_email: Optional[bool] = None,
        has_phone: Optional[bool] = None,
        has_website: Optional[bool] = None,
        bbb_accredited: Optional[bool] = None,
        min_rating: Optional[float] = None,
        min_review_count: Optional[int] = None,
        min_years: Optional[int] = None,
    ):
        self._params = {
            "job_id": job_id,
            "city": city,
            "tier": tier,
            "license_status": license_status,
            "search": search,
            "business_name": business_name,
            "zip_code": zip_code,
            "address": address,
            "owner_name": owner_name,
            "bbb_rating": bbb_rating,
            "specialty_keywords": specialty_keywords,
            "google_categories": google_categories,
            "services_listed": services_listed,
            "license_numbers": license_numbers,
            "license_categories": license_categories,
            "sources": sources,
            "place_ids": place_ids,
            "has_email": has_email,
            "has_phone": has_phone,
            "has_website": has_website,
            "bbb_accredited": bbb_accredited,
            "min_rating": min_rating,
            "min_review_count": min_review_count,
            "min_years": min_years,
        }

    def to_dict(self) -> dict:
        return self._params


@router.get("")
async def list_contractors(
    filters: ContractorFilters = Depends(),
    sort_by: str = "id",
    sort_dir: str = "desc",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    sort_col = sort_by if sort_by in SORTABLE else "id"
    return db.list_contractors(
        filters=filters.to_dict(),
        sort_by=sort_col,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
    )


EXPORT_COLUMNS = [
    "id", "business_name", "record_type", "canonical_entity_id",
    "city", "zip_code", "state", "county", "address",
    "tier", "city_tier", "specialty_keywords", "google_categories", "services_listed",
    "phone", "email", "website", "owner_name",
    "license_status", "license_numbers", "license_categories",
    "is_big_box", "vendor_type", "canonical_network",
    "google_rating", "google_review_count",
    "bbb_rating", "bbb_accredited", "years_in_business",
    "social_profiles", "sources", "source",
    "enrichment_status", "excluded_reason", "out_of_territory", "place_ids",
    "scraped_at", "job_id",
]


def _csv_cell(value):
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


EXPORT_FORMATS = {"csv", "xlsx"}


@router.get("/export")
async def export_contractors(
    filters: ContractorFilters = Depends(),
    sort_by: str = "id",
    sort_dir: str = "desc",
    format: str = Query("csv", description="csv | xlsx"),
    include_excluded: bool = Query(False, description="include lumber/out-of-territory rows (audit)"),
):
    """Download the DELIVERABLE contractor set as CSV or Excel. By default this
    drops lumber-excluded + out-of-territory rows (the clean output list). Pass
    include_excluded=true to export everything (audit). No pagination."""
    fmt = (format or "csv").lower()
    if fmt not in EXPORT_FORMATS:
        raise HTTPException(status_code=422, detail=f"format must be one of {sorted(EXPORT_FORMATS)}")
    sort_col = sort_by if sort_by in SORTABLE else "id"
    fd = filters.to_dict()
    fd["include_excluded"] = include_excluded
    fd["include_out_of_territory"] = include_excluded
    rows_iter = lambda: db.iter_contractors_filtered(
        filters=fd, sort_by=sort_col, sort_dir=sort_dir,
    )

    if fmt == "xlsx":
        return _export_xlsx(rows_iter)
    return _export_csv(rows_iter)


def _export_csv(rows_iter):
    def row_iter():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(EXPORT_COLUMNS)
        yield buf.getvalue()
        buf.seek(0); buf.truncate(0)
        for row in rows_iter():
            writer.writerow([_csv_cell(row.get(col)) for col in EXPORT_COLUMNS])
            if buf.tell() > 64 * 1024:
                yield buf.getvalue()
                buf.seek(0); buf.truncate(0)
        if buf.tell():
            yield buf.getvalue()

    filename = f"contractors_{date.today().isoformat()}.csv"
    return StreamingResponse(
        row_iter(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )


def _export_xlsx(rows_iter):
    """Build an .xlsx in memory. openpyxl write_only mode keeps peak RAM low by
    streaming rows to the sheet instead of holding a full cell grid."""
    from openpyxl import Workbook

    wb = Workbook(write_only=True)
    ws = wb.create_sheet(title="Contractors")
    ws.append(EXPORT_COLUMNS)
    for row in rows_iter():
        # Reuse the CSV cell formatter so lists/dicts/dates render identically.
        ws.append([_csv_cell(row.get(col)) for col in EXPORT_COLUMNS])

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    filename = f"contractors_{date.today().isoformat()}.xlsx"
    return StreamingResponse(
        out,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/facets")
async def facets(job_id: Optional[str] = None):
    return db.contractor_facets(job_id)


@router.get("/{contractor_id}")
async def get_contractor(contractor_id: int):
    row = db.get_contractor(contractor_id)
    if not row:
        raise HTTPException(status_code=404, detail="Contractor not found")
    return row


@router.get("/{contractor_id}/classification")
async def contractor_classification(contractor_id: int):
    """Audit trail for one contractor — the "why included" details."""
    row = db.get_contractor(contractor_id)
    if not row:
        raise HTTPException(status_code=404, detail="Contractor not found")
    return db.get_contractor_classification(contractor_id)


@router.get("/{contractor_id}/sources")
async def contractor_sources(contractor_id: int):
    """Per-source raw provenance for one contractor (Workstream E) — which sources
    (Google/BBB/license/Apollo) produced this business, linked by canonical_entity_id."""
    row = db.get_contractor(contractor_id)
    if not row:
        raise HTTPException(status_code=404, detail="Contractor not found")
    ceid = row.get("canonical_entity_id")
    return db.list_source_records(ceid) if ceid else []
