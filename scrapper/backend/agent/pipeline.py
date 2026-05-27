# pipeline.py
# Orchestrator — production scraper pattern.
# Reads job row, loops over metros, calls processor.process_metro per city,
# then runs global dedupe + export.

import os
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

from agent.db import update_job, get_active_keywords, list_cities
from agent.processor import process_metro
from agent.dedupe import dedupe_all_for_job
from agent.dbpr_loader import ensure_dbpr_loaded

# Process metros concurrently. Combined with per-row enrichment workers
# (processor.ENRICH_WORKERS), peak Apify concurrency ≈ METRO_WORKERS × ENRICH_WORKERS,
# so keep the product within the Apify plan's concurrency limit.
METRO_WORKERS = int(os.getenv("METRO_WORKERS", "6"))


def _load_cities():
    """Cities are sourced from the DB (seeded from cities.yaml on first boot, editable via UI)."""
    return list_cities()


def run_pipeline(job_id: str) -> None:
    """
    Main pipeline orchestrator. Called by FastAPI /api/jobs/start endpoint
    as a background asyncio task (see api/job_manager.py).
    """
    print(f"\n🚀 Pipeline START — job_id={job_id}")
    update_job(job_id, status="running", current_stage="init")

    try:
        # Snapshot active keywords at job start (reproducibility)
        active_kw = get_active_keywords()
        update_job(job_id, keywords_snapshot=active_kw)

        # First-time bootstrap of the DBPR bulk table (no-op once populated).
        ensure_dbpr_loaded()

        cities = _load_cities()
        progress = {}
        update_job(job_id, current_stage=f"scraping {len(cities)} metros (parallel)")

        # Process metros concurrently — each runs its full stage chain + DB inserts.
        def _run_metro(city):
            name = city["name"]
            try:
                summary = process_metro(city, job_id)
                return name, {"status": "done", "rows_in": summary["seeds"], "rows_out": summary["saved"]}
            except Exception as e:
                print(f"❌ Metro {name} failed: {e}")
                traceback.print_exc()
                return name, {"status": "failed", "error": str(e)}

        with ThreadPoolExecutor(max_workers=METRO_WORKERS) as ex:
            futures = [ex.submit(_run_metro, c) for c in cities]
            for fut in as_completed(futures):
                name, result = fut.result()
                progress[f"metro:{name}"] = result
                update_job(job_id, stages_progress=progress)

        # Global dedupe
        print("\n🔁 Stage 5: Global Dedupe (cross-metro)")
        update_job(job_id, current_stage="dedupe")
        dedupe_all_for_job(job_id)
        progress["stage5_dedupe"] = {"status": "done"}

        # Stage 8 (Export) is served on-demand from the DB via
        # GET /api/contractors/export (full = master, ?city=... = per-city).
        # No disk files are written — Cloud Run's filesystem is ephemeral.

        update_job(
            job_id,
            status="completed",
            current_stage="completed",
            stages_progress=progress,
        )
        print(f"\n🎯 Pipeline COMPLETED — job_id={job_id}")

    except Exception as e:
        traceback.print_exc()
        update_job(job_id, status="failed", error=str(e))
        print(f"\n❌ Pipeline FAILED — job_id={job_id}: {e}")
