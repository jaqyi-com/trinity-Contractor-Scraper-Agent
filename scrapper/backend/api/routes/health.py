# api/routes/health.py
# /api/health endpoint — used by cron-job.org to keep Render service awake.

from fastapi import APIRouter
from agent.db import _get_conn

router = APIRouter()


@router.get("/health")
async def health():
    """Health check. Reports DB connectivity."""
    db_ok = False
    try:
        conn = _get_conn()
        conn.close()
        db_ok = True
    except Exception:
        pass

    return {
        "status": "ok",
        "db": "connected" if db_ok else "disconnected",
    }
