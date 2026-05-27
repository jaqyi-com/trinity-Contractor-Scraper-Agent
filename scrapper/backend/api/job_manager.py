# api/job_manager.py
# asyncio background task manager — runs pipeline outside HTTP request cycle.
# Pipeline is sync (production scraper pattern), so we wrap with run_in_executor.

import asyncio
from concurrent.futures import ThreadPoolExecutor
from agent.pipeline import run_pipeline

_executor = ThreadPoolExecutor(max_workers=2)


async def start_background_job(job_id: str) -> None:
    """Kick off pipeline in a separate thread. Returns immediately."""
    loop = asyncio.get_running_loop()
    # Don't await — let it run forever in background
    loop.run_in_executor(_executor, run_pipeline, job_id)
