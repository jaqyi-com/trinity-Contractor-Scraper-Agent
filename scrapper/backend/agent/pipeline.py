# pipeline.py
# Orchestrator — production scraper pattern.
# Reads job row, loops over metros, calls processor.process_metro per city,
# then runs global dedupe + export.

import traceback

from agent.db import update_job, get_active_keywords, list_cities
from agent.processor import process_metro
from agent.dedupe import dedupe_all_for_job
from agent.exporter import export_all


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

        cities = _load_cities()
        progress = {}

        # Loop over metros
        for city in cities:
            city_name = city["name"]
            try:
                update_job(job_id, current_stage=f"metro:{city_name}")
                summary = process_metro(city, job_id)
                progress[f"metro:{city_name}"] = {
                    "status": "done",
                    "rows_in": summary["seeds"],
                    "rows_out": summary["saved"],
                }
                update_job(job_id, stages_progress=progress)
            except Exception as e:
                print(f"❌ Metro {city_name} failed: {e}")
                traceback.print_exc()
                progress[f"metro:{city_name}"] = {"status": "failed", "error": str(e)}
                update_job(job_id, stages_progress=progress)
                # Continue with next metro — don't crash whole pipeline

        # Global dedupe
        print("\n🔁 Stage 5: Global Dedupe (cross-metro)")
        update_job(job_id, current_stage="dedupe")
        dedupe_all_for_job(job_id)
        progress["stage5_dedupe"] = {"status": "done"}

        # Export
        print("\n📦 Stage 8: Export")
        update_job(job_id, current_stage="export")
        export_all(job_id)
        progress["stage8_export"] = {"status": "done"}

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
