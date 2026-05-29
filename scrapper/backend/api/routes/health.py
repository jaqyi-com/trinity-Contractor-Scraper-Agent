# api/routes/health.py
# /api/health endpoint — used by cron-job.org to keep Render service awake.

from fastapi import APIRouter

from agent.db import ping

router = APIRouter()


@router.get("/health")
async def health():
    """Health check. Reports storage (Google Sheets) connectivity."""
    return {
        "status": "ok",
        "db": "connected" if ping() else "disconnected",
    }
