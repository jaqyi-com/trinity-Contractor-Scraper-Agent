# pipeline.py
# Phased orchestrator with stop/resume support.
#
#   Phase 1  Discovery   — scrape every metro (parallel). Google = paid per place.
#   Phase 2  Dedupe seeds — collapse duplicates BEFORE enrichment (saves credits).
#   Phase 3  Classify     — tier each unique seed (free, pure Python).
#   Phase 4  Cap          — keep at most `max_final_records` best INCLUDED rows.
#   Phase 5  Enrich+save  — DBPR match + BBB/Apollo (paid per row) + UPSERT.
#   Phase 6  Dedupe sweep — post-insert belt-and-suspenders.
#
# Stop/Resume:
#   After every phase the working row-set is checkpointed (agent/checkpoint.py)
#   to the non-mirrored stage_outputs tab, and jobs.resume_from records the NEXT
#   phase. A stop is honoured at phase BOUNDARIES (we can't cleanly interrupt a
#   running Apify scrape mid-flight) — so the expensive discovery never re-runs.
#   Resume reloads the checkpoint and continues from resume_from.

import os
import traceback
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from agent.db import (
    update_job, get_job, get_active_keywords, list_cities, get_max_final_records,
    is_stop_requested, clear_job_stop,
)
from agent.processor import discover_metro, classify_seeds, enrich_and_insert_rows
from agent.scraper_dbpr import fetch_licenses_for_seeds
from agent.dedupe import dedupe_seeds, dedupe_all_for_job
from agent.checkpoint import save_checkpoint, load_checkpoint, clear_checkpoint

# Discover metros concurrently. Combined with per-row enrichment workers
# (processor.ENRICH_WORKERS), peak Apify concurrency ≈ METRO_WORKERS × ENRICH_WORKERS,
# so keep the product within the Apify plan's concurrency limit.
METRO_WORKERS = int(os.getenv("METRO_WORKERS", "6"))

# Ordered phases. Resume starts at one of these (resume_from); a fresh run starts
# at "discovery". "dedupe_final" needs no carried payload (data is already in the
# contractors tab by then).
PHASE_ORDER = ["discovery", "dedupe_seeds", "classify", "cap", "enrich", "dedupe_final"]

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


def _stop_requested(job_id: str, progress: dict) -> bool:
    """Check the stop flag (set by POST /jobs/{id}/stop, stored in job_control).
    If set, mark the job paused and return True so the caller bails out cleanly.
    resume_from + the stage checkpoint are already saved by the time we get here,
    so the pause is instant — no extra work to do."""
    if is_stop_requested(job_id):
        clear_job_stop(job_id)
        update_job(job_id, status="paused", current_stage="paused", stages_progress=progress)
        job = get_job(job_id)
        print(f"⏸️  Pipeline PAUSED — job_id={job_id} (resume_from={(job or {}).get('resume_from')})")
        return True
    return False


def _discover_all(job_id: str, cities, progress: dict):
    """Phase 1 across all metros (parallel)."""
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

    return all_seeds


def run_pipeline(job_id: str, start_at: str = "discovery", carried=None) -> None:
    """Main pipeline orchestrator. `start_at` + `carried` let it resume from a
    checkpointed phase; a fresh run uses the defaults. Called from
    api/job_manager.py (start) and resume_pipeline (resume)."""
    label = "START" if start_at == "discovery" else f"RESUME@{start_at}"
    print(f"\n🚀 Pipeline {label} — job_id={job_id}")
    clear_job_stop(job_id)  # fresh slate — drop any stale stop flag
    update_job(job_id, status="running", error="")
    if start_at == "discovery":
        update_job(job_id, current_stage="init")

    try:
        si = PHASE_ORDER.index(start_at)
        job = get_job(job_id) or {}
        progress = job.get("stages_progress") or {}

        # Keywords: snapshot at first start for reproducibility; reuse on resume.
        keywords = job.get("keywords_snapshot")
        if not keywords:
            keywords = get_active_keywords()
            update_job(job_id, keywords_snapshot=keywords)

        max_final = get_max_final_records()  # DB setting, default 5000
        cities = list_cities()

        # Carried payload maps to the variable the resumed phase consumes.
        seeds = carried if start_at == "dedupe_seeds" else None
        unique_seeds = carried if start_at == "classify" else None
        included = carried if start_at == "cap" else None
        rows = carried if start_at == "enrich" else None
        enrich_summary = {"saved": 0}

        # ─── Phase 1: Discovery ───
        if si <= PHASE_ORDER.index("discovery"):
            seeds = _discover_all(job_id, cities, progress)
            save_checkpoint(job_id, "dedupe_seeds", seeds)
            update_job(job_id, resume_from="dedupe_seeds", stages_progress=progress)
            if _stop_requested(job_id, progress):
                return

        # ─── Phase 2: Dedupe seeds (pre-enrichment cost saver) ───
        if si <= PHASE_ORDER.index("dedupe_seeds"):
            print("\n🧹 Phase 2: Dedupe seeds (pre-enrichment)")
            update_job(job_id, current_stage="dedupe_seeds")
            seeds = seeds or []
            unique_seeds = dedupe_seeds(seeds)
            progress["dedupe_seeds"] = {
                "raw": len(seeds),
                "unique": len(unique_seeds),
                "removed": len(seeds) - len(unique_seeds),
            }
            save_checkpoint(job_id, "classify", unique_seeds)
            update_job(job_id, resume_from="classify", stages_progress=progress)
            if _stop_requested(job_id, progress):
                return

        # ─── Phase 3: Classify (free) ───
        if si <= PHASE_ORDER.index("classify"):
            print("\n🏷️  Phase 3: Classify + Audit Log")
            update_job(job_id, current_stage="classify")
            unique_seeds = unique_seeds or []
            included = classify_seeds(unique_seeds, keywords, job_id)
            progress["classify"] = {
                "scanned": len(unique_seeds),
                "included": len(included),
                "excluded": len(unique_seeds) - len(included),
            }
            save_checkpoint(job_id, "cap", included)
            update_job(job_id, resume_from="cap", stages_progress=progress)
            if _stop_requested(job_id, progress):
                return

        # ─── Phase 4: Cap to max_final_records ───
        if si <= PHASE_ORDER.index("cap"):
            included = included or []
            rows = _apply_cap(included, max_final)
            print(f"\n🎚️  Phase 4: Cap — limit={max_final}, kept {len(rows)}/{len(included)} included")
            update_job(job_id, current_stage="cap")
            progress["cap"] = {
                "limit": max_final,
                "kept": len(rows),
                "dropped": len(included) - len(rows),
            }
            save_checkpoint(job_id, "enrich", rows)
            update_job(job_id, resume_from="enrich", stages_progress=progress)
            if _stop_requested(job_id, progress):
                return

        # ─── Phase 5: DBPR match + enrich + insert (paid per row) ───
        if si <= PHASE_ORDER.index("enrich"):
            rows = rows or []
            print(f"\n🏛️💎 Phase 5: DBPR + Enrich + Insert — {len(rows)} rows")
            update_job(job_id, current_stage="enrich")
            dbpr_index = fetch_licenses_for_seeds(rows)  # rows expose .business_name
            enrich_summary = enrich_and_insert_rows(rows, dbpr_index, job_id)
            progress["enrich"] = {"status": "done", "saved": enrich_summary["saved"]}
            # Data is now persisted to the contractors tab — dedupe_final carries nothing.
            save_checkpoint(job_id, "dedupe_final", [])
            update_job(job_id, resume_from="dedupe_final", stages_progress=progress)
            if _stop_requested(job_id, progress):
                return

        # ─── Phase 6: Global dedupe sweep (belt-and-suspenders) ───
        print("\n🔁 Phase 6: Global Dedupe (post-insert sweep)")
        update_job(job_id, current_stage="dedupe")
        dedupe_all_for_job(job_id)
        progress["dedupe_final"] = {"status": "done"}
        clear_checkpoint()

        update_job(
            job_id,
            status="completed",
            current_stage="completed",
            stages_progress=progress,
            finished_at=datetime.utcnow(),
            resume_from="",
        )
        print(f"\n🎯 Pipeline COMPLETED — job_id={job_id} — {enrich_summary.get('saved', 0)} records saved")

    except Exception as e:
        traceback.print_exc()
        # Leave resume_from intact so a transient failure (rate limit, DBPR
        # download) can be resumed instead of restarting from scratch.
        update_job(job_id, status="failed", error=str(e), finished_at=datetime.utcnow())
        print(f"\n❌ Pipeline FAILED — job_id={job_id}: {e}")


def resume_pipeline(job_id: str) -> None:
    """Resume a paused/failed job from its checkpoint. Called from job_manager."""
    job = get_job(job_id)
    if not job:
        print(f"❌ resume: job {job_id} not found")
        return
    start_at = job.get("resume_from") or "discovery"
    cp = load_checkpoint()
    carried = cp["items"] if cp else None
    if cp and cp.get("stage") and cp["stage"] != start_at:
        print(f"⚠️  resume: checkpoint stage '{cp['stage']}' != job.resume_from "
              f"'{start_at}' — trusting checkpoint")
        start_at = cp["stage"]
    if start_at not in PHASE_ORDER:
        print(f"⚠️  resume: bad resume_from '{start_at}', restarting from discovery")
        start_at = "discovery"
        carried = None
    # If we're meant to resume mid-pipeline but the checkpoint is gone (cleared,
    # never written), the carried set would be empty — restart cleanly instead of
    # silently producing zero rows. (dedupe_final legitimately carries nothing.)
    if start_at not in ("discovery", "dedupe_final") and not carried:
        print(f"⚠️  resume: no checkpoint for '{start_at}' — restarting from discovery")
        start_at = "discovery"
        carried = None
    run_pipeline(job_id, start_at=start_at, carried=carried)
