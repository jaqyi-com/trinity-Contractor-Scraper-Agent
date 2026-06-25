# api/routes/jobs.py
# Jobs endpoints — start pipeline, poll status, list past.
# (CSV export is served separately by GET /api/contractors/export.)

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel

from agent.db import (
    create_job, get_job, list_jobs, get_running_job, update_job,
    request_job_stop, clear_job_stop,
)
from agent.checkpoint import clear_checkpoint
from api.job_manager import start_background_job, start_background_resume
from api.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])


class StartJobBody(BaseModel):
    mode: Optional[str] = "contractor"     # contractor | vendor
    territory: Optional[str] = "FL"        # FL | TN


@router.post("/start")
async def start_job(background_tasks: BackgroundTasks, body: Optional[StartJobBody] = None):
    """
    Kick off the full pipeline. Returns job_id immediately.
    Pipeline runs as background task — frontend polls /status/{job_id}.

    Body (optional): {mode: contractor|vendor, territory: FL|TN}. Defaults to
    contractor/FL — the original behaviour — so existing callers are unaffected.

    🛡️ Server-side guard: if another job is already pending/running,
    return 409 Conflict with the existing job_id. Prevents:
    - User double-clicking the button
    - Multiple browser tabs starting jobs
    - Direct curl/Postman hits while a job is active
    """
    existing = get_running_job()
    if existing:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "A job is already running",
                "existing_job_id": existing["job_id"],
                "status": existing["status"],
                "current_stage": existing.get("current_stage"),
                "started_at": str(existing.get("started_at")),
            },
        )

    b = body or StartJobBody()
    mode = (b.mode or "contractor").lower()
    territory = (b.territory or "FL").upper()
    if mode not in ("contractor", "vendor"):
        raise HTTPException(status_code=422, detail=f"invalid mode {mode!r} (contractor|vendor)")
    if territory not in ("FL", "TN"):
        raise HTTPException(status_code=422, detail=f"invalid territory {territory!r} (FL|TN)")

    job_id = create_job(mode=mode, territory=territory)
    background_tasks.add_task(start_background_job, job_id)
    return {"job_id": job_id, "status": "pending", "mode": mode, "territory": territory}


@router.post("/{job_id}/stop")
async def stop_job(job_id: str):
    """Request a graceful stop. The pipeline checks this flag at the next phase
    boundary, checkpoints its progress, and moves the job to `paused`. The
    expensive discovery stage is never re-run on resume."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") not in ("pending", "running"):
        raise HTTPException(
            status_code=409,
            detail=f"Job is not running (status={job.get('status')}) — nothing to stop",
        )
    request_job_stop(job_id)  # control-tab flag; worker pauses at next stage boundary
    return {"job_id": job_id, "status": job.get("status"), "stop_requested": True}


@router.post("/{job_id}/resume")
async def resume_job(job_id: str, background_tasks: BackgroundTasks):
    """Resume a paused (or failed) job from its checkpoint."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") not in ("paused", "failed"):
        raise HTTPException(
            status_code=409,
            detail=f"Only a paused/failed job can be resumed (status={job.get('status')})",
        )
    # Don't resume into a collision with another active job.
    running = get_running_job()
    if running and running["job_id"] != job_id:
        raise HTTPException(
            status_code=409,
            detail={"error": "Another job is active", "existing_job_id": running["job_id"]},
        )
    update_job(job_id, status="running", stop_requested=False)
    background_tasks.add_task(start_background_resume, job_id)
    return {"job_id": job_id, "status": "running", "resume_from": job.get("resume_from")}


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Discard a paused job and free the slot for a new run. Clears its checkpoint."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") != "paused":
        raise HTTPException(
            status_code=409,
            detail=f"Only a paused job can be cancelled (status={job.get('status')}); stop it first",
        )
    update_job(job_id, status="cancelled", finished_at=datetime.utcnow(), resume_from="")
    clear_job_stop(job_id)
    try:
        clear_checkpoint()
    except Exception as e:
        print(f"⚠️  cancel: checkpoint clear failed: {e}")
    return {"job_id": job_id, "status": "cancelled"}


@router.get("/current")
async def current_job():
    """
    Returns currently running/pending job if any, else null.
    Frontend uses this on page-load to restore polling state after refresh.
    """
    job = get_running_job()
    return job  # None if no active job


@router.get("/{job_id}/status")
async def job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("")
async def list_all_jobs(limit: int = 50):
    return list_jobs(limit=limit)
