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
#   At the START of each phase, jobs.resume_from is set to THAT phase and the
#   phase's INPUT is checkpointed (agent/checkpoint.py) to the non-mirrored
#   stage_outputs tab — the input is just the previous (completed) phase's saved
#   output, so no extra work. A stop is then honoured MID-PHASE (polled inside the
#   discovery and enrichment loops): the pipeline bails immediately, DISCARDING the
#   in-progress phase's partial work. Resume reloads the last completed phase's
#   checkpoint and re-runs the interrupted phase from scratch.
#
#   We still can't tear a single in-flight Apify call out mid-request, so worst-case
#   stop latency ≈ one metro discovery / one enrichment wave — but the rest of the
#   phase never runs, and the phase is redone cleanly on resume.

import os
import traceback
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from agent.db import (
    update_job, get_job, get_active_keywords, list_cities, get_max_final_records,
    is_stop_requested, clear_job_stop,
)
from agent.processor import (
    discover_metro, classify_seeds, enrich_and_insert_rows, PipelineStopRequested,
)
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


def _check_stop(job_id: str) -> None:
    """Raise PipelineStopRequested if a stop has been requested (set by
    POST /jobs/{id}/stop, stored in job_control). resume_from already points at the
    in-progress phase, so the caught exception pauses the job and resume re-runs
    this phase from scratch on the last completed phase's checkpoint."""
    if is_stop_requested(job_id):
        raise PipelineStopRequested()


def _discover_all(job_id: str, cities, progress: dict):
    """Phase 1 across all metros (parallel). Polls the stop flag after each metro
    finishes; on stop it stops launching the remaining metros, discards what was
    gathered, and raises PipelineStopRequested. A single metro's Apify call already
    in flight can't be cancelled, but it just finishes in the background — the
    pipeline returns and the whole phase is redone on resume."""
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

    ex = ThreadPoolExecutor(max_workers=METRO_WORKERS)
    futures = [ex.submit(_discover, c) for c in cities]
    stopped = False
    try:
        for fut in as_completed(futures):
            name, seeds = fut.result()
            all_seeds.extend(seeds)
            progress[f"discovery:{name}"] = {"status": "done", "seeds": len(seeds)}
            update_job(job_id, stages_progress=progress)
            if is_stop_requested(job_id):
                stopped = True
                break
    finally:
        # Don't wait on in-flight metros; cancel any not yet started.
        ex.shutdown(wait=False, cancel_futures=True)

    if stopped:
        raise PipelineStopRequested()
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

        # Each phase: point resume_from at ITSELF first (so a mid-phase stop re-runs
        # THIS phase from scratch), then do the work, then checkpoint the NEXT phase's
        # input. The on-disk checkpoint already holds this phase's input — it was
        # written as the previous phase's "next-stage" save.

        # ─── Phase 1: Discovery ───
        if si <= PHASE_ORDER.index("discovery"):
            update_job(job_id, resume_from="discovery")
            clear_checkpoint()  # discovery has no carried input; re-runs fresh on resume
            seeds = _discover_all(job_id, cities, progress)  # raises on stop
            save_checkpoint(job_id, "dedupe_seeds", seeds)
            update_job(job_id, stages_progress=progress)

        # ─── Phase 2: Dedupe seeds (pre-enrichment cost saver) ───
        if si <= PHASE_ORDER.index("dedupe_seeds"):
            update_job(job_id, resume_from="dedupe_seeds", current_stage="dedupe_seeds")
            _check_stop(job_id)  # fast/uninterruptible phase — honour stop at its start
            print("\n🧹 Phase 2: Dedupe seeds (pre-enrichment)")
            seeds = seeds or []
            unique_seeds = dedupe_seeds(seeds)
            progress["dedupe_seeds"] = {
                "raw": len(seeds),
                "unique": len(unique_seeds),
                "removed": len(seeds) - len(unique_seeds),
            }
            save_checkpoint(job_id, "classify", unique_seeds)
            update_job(job_id, stages_progress=progress)

        # ─── Phase 3: Classify (free) ───
        if si <= PHASE_ORDER.index("classify"):
            update_job(job_id, resume_from="classify", current_stage="classify")
            _check_stop(job_id)
            print("\n🏷️  Phase 3: Classify + Audit Log")
            unique_seeds = unique_seeds or []
            included = classify_seeds(unique_seeds, keywords, job_id)
            progress["classify"] = {
                "scanned": len(unique_seeds),
                "included": len(included),
                "excluded": len(unique_seeds) - len(included),
            }
            save_checkpoint(job_id, "cap", included)
            update_job(job_id, stages_progress=progress)

        # ─── Phase 4: Cap to max_final_records ───
        if si <= PHASE_ORDER.index("cap"):
            update_job(job_id, resume_from="cap", current_stage="cap")
            _check_stop(job_id)
            included = included or []
            rows = _apply_cap(included, max_final)
            print(f"\n🎚️  Phase 4: Cap — limit={max_final}, kept {len(rows)}/{len(included)} included")
            progress["cap"] = {
                "limit": max_final,
                "kept": len(rows),
                "dropped": len(included) - len(rows),
            }
            save_checkpoint(job_id, "enrich", rows)
            update_job(job_id, stages_progress=progress)

        # ─── Phase 5: DBPR match + enrich + insert (paid per row) ───
        if si <= PHASE_ORDER.index("enrich"):
            update_job(job_id, resume_from="enrich", current_stage="enrich")
            _check_stop(job_id)
            rows = rows or []
            print(f"\n🏛️💎 Phase 5: DBPR + Enrich + Insert — {len(rows)} rows")
            dbpr_index = fetch_licenses_for_seeds(rows)  # rows expose .business_name
            enrich_summary = enrich_and_insert_rows(
                rows, dbpr_index, job_id, should_stop=lambda: is_stop_requested(job_id)
            )  # raises on stop (nothing persisted until it finishes the row set)
            progress["enrich"] = {"status": "done", "saved": enrich_summary["saved"]}
            # Data is now persisted to the contractors tab — dedupe_final carries nothing.
            save_checkpoint(job_id, "dedupe_final", [])
            update_job(job_id, stages_progress=progress)

        # ─── Phase 6: Global dedupe sweep (belt-and-suspenders) ───
        update_job(job_id, resume_from="dedupe_final", current_stage="dedupe")
        _check_stop(job_id)
        print("\n🔁 Phase 6: Global Dedupe (post-insert sweep)")
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

    except PipelineStopRequested:
        # Mid-phase stop: the in-progress phase's partial work is discarded.
        # resume_from already points at that phase and its input checkpoint is on
        # disk, so Resume re-runs it from scratch. Pause is instant — no save needed.
        clear_job_stop(job_id)
        job = get_job(job_id) or {}
        update_job(job_id, status="paused", current_stage="paused", stages_progress=progress)
        print(f"⏸️  Pipeline PAUSED — job_id={job_id} "
              f"(resume_from={job.get('resume_from')}) — in-progress stage discarded")

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
