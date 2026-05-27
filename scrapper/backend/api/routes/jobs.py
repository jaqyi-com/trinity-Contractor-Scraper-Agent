# api/routes/jobs.py
# Jobs endpoints — start pipeline, poll status, list past, download exports.

import os
from pathlib import Path
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from fastapi.responses import FileResponse

from agent.db import create_job, get_job, list_jobs, get_running_job
from api.job_manager import start_background_job
from api.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])

EXPORT_DIR = os.getenv("EXPORT_DIR", "./exports")


@router.post("/start")
async def start_job(background_tasks: BackgroundTasks):
    """
    Kick off the full pipeline. Returns job_id immediately.
    Pipeline runs as background task — frontend polls /status/{job_id}.

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

    job_id = create_job()
    background_tasks.add_task(start_background_job, job_id)
    return {"job_id": job_id, "status": "pending"}


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


@router.get("/{job_id}/download/{filename}")
async def download_export(job_id: str, filename: str):
    path = Path(EXPORT_DIR) / job_id / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"File {filename} not found")
    return FileResponse(path, filename=filename)
