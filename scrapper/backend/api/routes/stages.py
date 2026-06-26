# api/routes/stages.py
# Workstream E — pipeline stage layers (raw → normalized → enriched → filtered →
# deliverable), stored per batch. Read-only views for the Pipeline Stages UI.
# All require JWT (router-level dependency).

import csv
import io
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from agent.db import list_stage_batches, list_stage_records, STAGE_ORDER
from api.auth import get_current_user
# Reuse the contractor export schema + cell formatter so a stage snapshot exports
# the SAME full column set as the final deliverable (every Workstream E tag).
from api.routes.contractors import EXPORT_COLUMNS, _csv_cell

router = APIRouter(dependencies=[Depends(get_current_user)])

# Stage rows carry batch/stage metadata on top of the full record snapshot (`data`).
STAGE_EXPORT_COLUMNS = ["batch_name", "stage", *EXPORT_COLUMNS]


@router.get("/order")
async def stage_order():
    """The canonical stage order (for the UI's tab order)."""
    return {"stages": list(STAGE_ORDER)}


@router.get("/batches")
async def batches_endpoint():
    """Batches that have stage snapshots, each with per-stage row counts."""
    return list_stage_batches()


@router.get("/records")
async def records_endpoint(
    batch: str = Query(...),
    stage: str = Query(...),
    limit: int = Query(1000, ge=1, le=5000),
):
    """Records stored at one (batch, stage). Each row includes `data` — the full
    record snapshot — so the UI can show every column, not just the indexed ones."""
    rows = list_stage_records(batch, stage, limit=limit)
    return {"batch": batch, "stage": stage, "total": len(rows), "rows": rows}


def _stage_cell(row: dict, col: str):
    """Pull a column from a stage row: prefer the full `data` snapshot, fall back to
    the indexed top-level field (batch_name/stage live only at top level)."""
    data = row.get("data") or {}
    if col in ("batch_name", "stage"):
        return row.get(col)
    return data.get(col, row.get(col))


@router.get("/export")
async def export_stage(
    batch: str = Query(...),
    stage: str = Query(...),
    limit: int = Query(5000, ge=1, le=5000),
):
    """Download one (batch, stage) snapshot as CSV — the SAME full column set as the
    contractor/vendor deliverable, plus batch_name + stage. Unlike the final export
    this includes excluded/out-of-territory rows, because a stage layer is the audit
    view of exactly what existed at that point in the pipeline."""
    rows = list_stage_records(batch, stage, limit=limit)
    if not rows:
        raise HTTPException(status_code=404, detail="No records at this batch/stage")
    batch_name = (rows[0].get("batch_name") or batch)

    def row_iter():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(STAGE_EXPORT_COLUMNS)
        yield buf.getvalue()
        buf.seek(0); buf.truncate(0)
        for row in rows:
            writer.writerow([_csv_cell(_stage_cell(row, c)) for c in STAGE_EXPORT_COLUMNS])
            if buf.tell() > 64 * 1024:
                yield buf.getvalue()
                buf.seek(0); buf.truncate(0)
        if buf.tell():
            yield buf.getvalue()

    safe = "".join(ch if ch.isalnum() else "_" for ch in str(batch_name))[:40]
    filename = f"stage_{stage}_{safe}_{date.today().isoformat()}.csv"
    return StreamingResponse(
        row_iter(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )
