# run_job.py
# Cloud Run Job entrypoint — runs ONE pipeline execution to completion, then exits.
#
# A Cloud Run Job runs this container command instead of the FastAPI server:
#     python -m agent.run_job
# The API service triggers an execution with per-run env overrides:
#     JOB_ID  — the job to run (required)
#     RESUME  — "true" to resume from the saved checkpoint, else a fresh run
#
# This is a separate process from the API service; both share the same Google
# Sheet as state. See agent/db.py (_runner_is_job / _is_job_worker) for how the
# service reads this worker's live progress without clobbering it.

import os
import sys

from agent.db import init_schema
from agent.pipeline import run_pipeline, resume_pipeline
from agent.sheets_client import get_db


def main() -> int:
    job_id = os.environ.get("JOB_ID")
    if not job_id:
        print("❌ run_job: JOB_ID env var not set — nothing to run")
        return 2

    resume = os.environ.get("RESUME", "").strip().lower() in ("1", "true", "yes")
    print(f"🧩 Cloud Run Job execution — job_id={job_id} resume={resume}")

    # Fresh container: bootstrap the Sheets connection + mirror for this process.
    init_schema()

    try:
        if resume:
            resume_pipeline(job_id)
        else:
            run_pipeline(job_id)
        return 0
    finally:
        # Drain any buffered writes before the container exits (the flusher is a
        # daemon thread and would otherwise be killed mid-flight).
        try:
            get_db().flush_all()
        except Exception as e:
            print(f"⚠️  run_job: final flush failed: {e}")


if __name__ == "__main__":
    sys.exit(main())
