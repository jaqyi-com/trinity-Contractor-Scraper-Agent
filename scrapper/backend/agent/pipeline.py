# pipeline.py
# Phased orchestrator.
#
#   Phase 1  Discovery   — scrape every metro (parallel). Google = paid per place.
#   Phase 2  Dedupe seeds — collapse duplicates BEFORE enrichment (saves credits).
#   Phase 3  Classify     — tier each unique seed (free, pure Python).
#   Phase 4  Cap          — keep at most `max_final_records` best INCLUDED rows
#                           (DB-configured, default 5000) so enrichment cost is
#                           bounded and the run returns a predictable count.
#   Phase 5  Enrich+save  — DBPR match + BBB/Apollo (paid per row) + UPSERT.
#   Phase 6  Dedupe sweep — post-insert belt-and-suspenders.

import os
import traceback
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from agent.db import (
    update_job, get_active_keywords, list_cities, get_max_final_records,
)
from agent.processor import discover_metro, classify_seeds, enrich_and_insert_rows
from agent.scraper_dbpr import fetch_licenses_for_seeds
from agent.dedupe import dedupe_seeds, dedupe_all_for_job
from agent.dbpr_loader import refresh_dbpr_licenses

# Discover metros concurrently. Combined with per-row enrichment workers
# (processor.ENRICH_WORKERS), peak Apify concurrency ≈ METRO_WORKERS × ENRICH_WORKERS,
# so keep the product within the Apify plan's concurrency limit.
METRO_WORKERS = int(os.getenv("METRO_WORKERS", "6"))

# When over the cap, keep the strongest leads first. Lower rank = kept first.
_TIER_RANK = {
    "TIER_1_DRYWALL": 0,
    "TIER_1_GC_WITH_SCOPE": 1,
    "TIER_2_PAINTER": 2,
    "TIER_2_REMODELER": 3,
    "TIER_2_GC_GENERIC": 4,
    "TIER_3_HANDYMAN": 5,
}


def _apply_cap(rows, limit):
    """Keep at most `limit` rows, prioritising tier then Google rating so the
    dropped rows are the weakest leads. limit<=0 / None means no cap."""
    if not limit or limit <= 0 or len(rows) <= limit:
        return rows
    ranked = sorted(rows, key=lambda r: (_TIER_RANK.get(r.tier, 9), -(r.google_rating or 0.0)))
    return ranked[:limit]


def run_pipeline(job_id: str) -> None:
    """Main pipeline orchestrator. Called by FastAPI /api/jobs/start as a
    background task (see api/job_manager.py)."""
    print(f"\n🚀 Pipeline START — job_id={job_id}")
    update_job(job_id, status="running", current_stage="init")

    try:
        # Snapshot active keywords at job start (reproducibility)
        keywords = get_active_keywords()
        update_job(job_id, keywords_snapshot=keywords)

        # Refresh the DBPR bulk table from the official CSV at the start of every
        # run, so license tagging always uses fresh data (this replaces the old
        # weekly cron). Non-fatal: the CSV is downloaded+parsed before the table
        # is touched, so a download failure leaves the previous table intact and
        # Stage 2 falls back to the Apify DBPR verifier — never block the pipeline.
        update_job(job_id, current_stage="dbpr_refresh")
        try:
            refresh_dbpr_licenses()
        except Exception as e:
            print(f"⚠️  [DBPR] refresh skipped, using existing table: {e}")
            traceback.print_exc()

        max_final = get_max_final_records()  # DB setting, default 5000
        cities = list_cities()
        progress = {}

        # ─── Phase 1: Discovery (parallel across metros) ───
        update_job(job_id, current_stage=f"discovery ({len(cities)} metros, parallel)")
        all_seeds = []

        def _discover(city):
            name = city["name"]
            try:
                return name, discover_metro(city, job_id)
            except Exception as e:
                print(f"❌ Discovery {name} failed: {e}")
                traceback.print_exc()
                return name, []

        with ThreadPoolExecutor(max_workers=METRO_WORKERS) as ex:
            for fut in as_completed([ex.submit(_discover, c) for c in cities]):
                name, seeds = fut.result()
                all_seeds.extend(seeds)
                progress[f"discovery:{name}"] = {"status": "done", "seeds": len(seeds)}
                update_job(job_id, stages_progress=progress)

        # ─── Phase 2: Dedupe seeds (BEFORE enrichment — the cost saver) ───
        print("\n🧹 Phase 2: Dedupe seeds (pre-enrichment)")
        update_job(job_id, current_stage="dedupe_seeds")
        unique_seeds = dedupe_seeds(all_seeds)
        progress["dedupe_seeds"] = {
            "raw": len(all_seeds),
            "unique": len(unique_seeds),
            "removed": len(all_seeds) - len(unique_seeds),
        }
        update_job(job_id, stages_progress=progress)

        # ─── Phase 3: Classify (free) ───
        print("\n🏷️  Phase 3: Classify + Audit Log")
        update_job(job_id, current_stage="classify")
        included = classify_seeds(unique_seeds, keywords, job_id)
        progress["classify"] = {
            "scanned": len(unique_seeds),
            "included": len(included),
            "excluded": len(unique_seeds) - len(included),
        }
        update_job(job_id, stages_progress=progress)

        # ─── Phase 4: Cap to max_final_records (bounds enrichment cost) ───
        rows = _apply_cap(included, max_final)
        print(f"\n🎚️  Phase 4: Cap — limit={max_final}, kept {len(rows)}/{len(included)} included")
        progress["cap"] = {
            "limit": max_final,
            "kept": len(rows),
            "dropped": len(included) - len(rows),
        }
        update_job(job_id, stages_progress=progress)

        # ─── Phase 5: DBPR match + enrich + insert (paid per row) ───
        print(f"\n🏛️💎 Phase 5: DBPR + Enrich + Insert — {len(rows)} rows")
        update_job(job_id, current_stage="enrich")
        dbpr_index = fetch_licenses_for_seeds(rows)  # rows expose .business_name
        enrich_summary = enrich_and_insert_rows(rows, dbpr_index, job_id)
        progress["enrich"] = {"status": "done", "saved": enrich_summary["saved"]}
        update_job(job_id, stages_progress=progress)

        # ─── Phase 6: Global dedupe sweep (belt-and-suspenders) ───
        print("\n🔁 Phase 6: Global Dedupe (post-insert sweep)")
        update_job(job_id, current_stage="dedupe")
        dedupe_all_for_job(job_id)
        progress["dedupe_final"] = {"status": "done"}

        update_job(
            job_id,
            status="completed",
            current_stage="completed",
            stages_progress=progress,
            finished_at=datetime.utcnow(),
        )
        print(f"\n🎯 Pipeline COMPLETED — job_id={job_id} — {enrich_summary['saved']} records saved")

    except Exception as e:
        traceback.print_exc()
        update_job(job_id, status="failed", error=str(e), finished_at=datetime.utcnow())
        print(f"\n❌ Pipeline FAILED — job_id={job_id}: {e}")
