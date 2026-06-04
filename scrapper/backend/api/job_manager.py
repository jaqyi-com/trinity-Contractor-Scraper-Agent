# api/job_manager.py
# Launches a pipeline run, outside the HTTP request cycle, in one of two modes
# (selected by the PIPELINE_RUNNER env var):
#
#   thread          (default) — run in a background thread of THIS process.
#                   Fine for local dev; on Cloud Run *services* it needs
#                   "CPU always allocated" + min-instances=1 to survive.
#   cloud_run_job   — trigger a separate Cloud Run JOB execution (full CPU for
#                   hours, no request-bound throttling). Production path.

import os
import asyncio
from concurrent.futures import ThreadPoolExecutor

from agent.pipeline import run_pipeline, resume_pipeline

_executor = ThreadPoolExecutor(max_workers=2)


def _use_cloud_run_job() -> bool:
    return os.getenv("PIPELINE_RUNNER", "thread").lower() == "cloud_run_job"


async def start_background_job(job_id: str) -> None:
    """Kick off a fresh pipeline run. Returns immediately."""
    if _use_cloud_run_job():
        from api.cloud_run_trigger import trigger_pipeline_job
        trigger_pipeline_job(job_id, resume=False)
        return
    loop = asyncio.get_running_loop()
    loop.run_in_executor(_executor, run_pipeline, job_id)


async def start_background_resume(job_id: str) -> None:
    """Resume a paused/failed pipeline from its checkpoint. Returns immediately."""
    if _use_cloud_run_job():
        from api.cloud_run_trigger import trigger_pipeline_job
        trigger_pipeline_job(job_id, resume=True)
        return
    loop = asyncio.get_running_loop()
    loop.run_in_executor(_executor, resume_pipeline, job_id)
