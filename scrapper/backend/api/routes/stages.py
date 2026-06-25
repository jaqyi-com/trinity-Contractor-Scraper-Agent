# api/routes/stages.py
# Workstream E — pipeline stage layers (raw → normalized → enriched → filtered →
# deliverable), stored per batch. Read-only views for the Pipeline Stages UI.
# All require JWT (router-level dependency).

from typing import Optional
from fastapi import APIRouter, Depends, Query

from agent.db import list_stage_batches, list_stage_records, STAGE_ORDER
from api.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])


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
    """Records stored at one (batch, stage)."""
    rows = list_stage_records(batch, stage, limit=limit)
    return {"batch": batch, "stage": stage, "total": len(rows), "rows": rows}
