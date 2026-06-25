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
    get_discovery_budget_usd, get_bbb_budget_usd, get_apollo_budget_usd,
    is_stop_requested, clear_job_stop, record_stage,
)
from agent.processor import (
    discover_metro, classify_seeds, enrich_and_insert_rows, PipelineStopRequested,
)
from agent.scraper_dbpr import fetch_licenses_for_seeds_by_state
from agent.dedupe import dedupe_seeds, dedupe_all_for_job
from agent.checkpoint import save_checkpoint, load_checkpoint, clear_checkpoint
from agent.schema import ContractorRow

# Discover metros concurrently. Combined with per-row enrichment workers
# (processor.ENRICH_WORKERS), peak Apify concurrency ≈ METRO_WORKERS × ENRICH_WORKERS,
# so keep the product within the Apify plan's concurrency limit.
METRO_WORKERS = int(os.getenv("METRO_WORKERS", "6"))

# Apify rejects a per-run maxTotalChargeUsd below this floor
# ("max-total-charge-usd-below-minimum"). We clamp each metro's budget slice up
# to it, so the smallest enforceable discovery ceiling is this × number of metros.
APIFY_MIN_CHARGE_USD = 0.50

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


def _resolve_run_plan(mode: str, territory: str, client_id: str = None) -> dict:
    """Map (mode, territory) → discovery plan: which cities to scrape, the search
    state, the query set, and the record_type. The default (contractor/FL) returns
    the original Florida city list + contractor queries, so it behaves exactly as
    before. TN/vendor pull from the geography/targeting config built in Phase 2."""
    mode = (mode or "contractor").lower()
    territory = (territory or "FL").upper()

    if mode == "vendor":
        from agent.targeting import vendor_scrape_units
        from agent.scraper_vendor import VENDOR_QUERIES
        units = vendor_scrape_units(territory)
        cities = [{"name": u["city"], "zips": u["zips"]} for u in units]
        return {"cities": cities, "state": territory, "queries": VENDOR_QUERIES, "record_type": "vendor"}

    # contractor mode
    if territory == "TN":
        from agent.targeting import contractor_scrape_units
        from agent.db import list_dealer_accounts
        dealers = list_dealer_accounts(client_id)
        if dealers:
            # Case 1 (spec): vendor/dealer accounts exist → scrape the ZIPs within the
            # contractor radius (50 mi) of each vendor account, deduped, Memphis-excluded.
            units = contractor_scrape_units("TN", client_id)
            cities = [{"name": u["city"], "zips": u["zips"]} for u in units]
            print(f"   TN contractor → {len(dealers)} vendor account(s): vendor-anchored ZIPs")
        else:
            # Case 2: no vendor accounts → fall back to Florida-style static city ZIPs
            # (the TN cities seeded into the cities/city_zips tabs).
            cities = [c for c in list_cities() if (c.get("state") or "").upper() == "TN"]
            print(f"   TN contractor → no vendor accounts: Florida-style city ZIPs ({len(cities)} cities)")
        return {"cities": cities, "state": "TN", "queries": None, "record_type": "contractor"}

    # contractor + FL — FL cities only (TN cities now live in the same cities tab,
    # so we must filter by state or an FL run would wrongly scrape TN metros too).
    fl_cities = [c for c in list_cities() if (c.get("state") or "FL").upper() == "FL"]
    return {"cities": fl_cities, "state": "FL", "queries": None, "record_type": "contractor"}


def _vendor_rows_from_seeds(seeds, state: str, client_id: str, job_id: str):
    """Vendor-mode replacement for the tier classifier: build a vendor ContractorRow
    per seed (alias roll-up + big-box flag + lumber flag handled in build_vendor_row)."""
    from agent.scraper_vendor import build_vendor_row
    fields = set(ContractorRow.model_fields)
    rows = []
    for s in seeds:
        # Seed-list distributors (place_id 'seed:*') are tagged source 'vendor_seed';
        # everything else came from live Google discovery.
        src = "vendor_seed" if str(getattr(s, "place_id", "")).startswith("seed:") else "google_business"
        d = build_vendor_row(s, state=state, client_id=client_id, source=src)
        d["job_id"] = job_id
        rows.append(ContractorRow(**{k: v for k, v in d.items() if k in fields}))
    return rows


def _tag_geo(rows, state: str, mode: str, client_id: str):
    """Stamp state + city_tier on each row from its ZIP (Tier-1 cities win). FL has
    no tiers so this only sets state there; TN gets the priority tier tag."""
    tmap = {}
    if (state or "").upper() == "TN":
        from agent.targeting import zip_tier_map
        tmap = zip_tier_map("TN", "vendor" if mode == "vendor" else "contractor", client_id)
    for r in rows:
        if not getattr(r, "state", None):
            r.state = state
        if getattr(r, "city_tier", None) is None and getattr(r, "zip_code", None):
            t = tmap.get(str(r.zip_code)[:5])
            if t is not None:
                r.city_tier = str(t)
    return rows


def _check_stop(job_id: str) -> None:
    """Raise PipelineStopRequested if a stop has been requested (set by
    POST /jobs/{id}/stop, stored in job_control). resume_from already points at the
    in-progress phase, so the caught exception pauses the job and resume re-runs
    this phase from scratch on the last completed phase's checkpoint."""
    if is_stop_requested(job_id):
        raise PipelineStopRequested()


def _discover_all(job_id: str, cities, progress: dict, discovery_budget_usd=None,
                  state: str = "FL", queries=None):
    """Phase 1 across all metros (parallel). Polls the stop flag after each metro
    finishes; on stop it stops launching the remaining metros, discards what was
    gathered, and raises PipelineStopRequested. A single metro's Apify call already
    in flight can't be cancelled, but it just finishes in the background — the
    pipeline returns and the whole phase is redone on resume.

    `discovery_budget_usd` (None = unlimited) is split evenly across metros and
    passed to each as Apify's maxTotalChargeUsd hard cap."""
    update_job(job_id, current_stage=f"discovery ({len(cities)} metros, parallel)")
    all_seeds = []
    per_metro_charge = None
    if discovery_budget_usd and cities:
        per_metro_charge = discovery_budget_usd / len(cities)
        # Apify enforces a $0.50 floor on maxTotalChargeUsd per run. If the budget
        # split lands below that, clamp up — the effective discovery ceiling becomes
        # $0.50 × metros, which can exceed the requested budget. (maxTotalChargeUsd
        # is a CEILING, not a target — actual spend is usually well under it.)
        if per_metro_charge < APIFY_MIN_CHARGE_USD:
            print(f"⚠️ Discovery budget ${discovery_budget_usd} ÷ {len(cities)} metros "
                  f"= ${per_metro_charge:.4f}/metro is below Apify's "
                  f"${APIFY_MIN_CHARGE_USD}/run minimum — clamping to "
                  f"${APIFY_MIN_CHARGE_USD}/metro (effective ceiling ≈ "
                  f"${APIFY_MIN_CHARGE_USD * len(cities):.2f}).")
            per_metro_charge = APIFY_MIN_CHARGE_USD
        print(f"💰 Discovery budget ${discovery_budget_usd} → "
              f"${per_metro_charge:.4f}/metro (Apify maxTotalChargeUsd, hard ceiling)")

    def _discover(city):
        name = city["name"]
        try:
            return name, discover_metro(city, job_id, max_charge_usd=per_metro_charge,
                                        state=state, queries=queries)
        except Exception as e:
            print(f"❌ Discovery {name} failed: {e}")
            traceback.print_exc()
            return name, []

    # Discovery is the expensive PAID stage — once started we let it FINISH all
    # metros even if a stop was requested mid-way, so the paid seeds are never
    # thrown away. The stop is honoured at the next phase boundary (Phase 2's
    # _check_stop), by which point the seeds are already checkpointed → Resume
    # picks up from dedupe_seeds and never re-pays for discovery.
    ex = ThreadPoolExecutor(max_workers=METRO_WORKERS)
    futures = [ex.submit(_discover, c) for c in cities]
    try:
        for fut in as_completed(futures):
            name, seeds = fut.result()
            all_seeds.extend(seeds)
            progress[f"discovery:{name}"] = {"status": "done", "seeds": len(seeds)}
            update_job(job_id, stages_progress=progress)
    finally:
        ex.shutdown(wait=True)

    if is_stop_requested(job_id):
        print(f"🛑 stop requested — discovery finished ({len(all_seeds)} seeds "
              f"collected & will be saved); pausing at next phase boundary")
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
        # Per-service USD cost budgets (None = unlimited). Read once per run.
        discovery_budget = get_discovery_budget_usd()
        bbb_budget = get_bbb_budget_usd()
        apollo_budget = get_apollo_budget_usd()

        # Run scope (Phase 6b): mode (contractor|vendor) + territory (FL|TN).
        mode = (job.get("mode") or "contractor").lower()
        territory = (job.get("territory") or "FL").upper()
        client_id = job.get("client_id")
        plan = _resolve_run_plan(mode, territory, client_id)
        cities = plan["cities"]
        print(f"🧭 Run scope: mode={mode} territory={territory} "
              f"→ {len(cities)} cities, state={plan['state']}, record_type={plan['record_type']}")

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
            seeds = _discover_all(job_id, cities, progress, discovery_budget,
                                  state=plan["state"], queries=plan["queries"])  # raises on stop
            # Vendor mode: fold in the seed-list distributors (validation/seed set) so
            # they're confirmed + enriched + merged with discovered ones via dedupe.
            if mode == "vendor":
                from agent.scraper_vendor import seed_distributor_seeds
                sd = seed_distributor_seeds()
                if sd:
                    seeds.extend(sd)
                    print(f"📥 Vendor seed set: folded in {len(sd)} seed distributors")
            record_stage(job_id, "discovery", seeds)  # Workstream E — Phase 1 snapshot (raw seeds)
            save_checkpoint(job_id, "dedupe_seeds", seeds)
            update_job(job_id, stages_progress=progress)

        # ─── Phase 2: Dedupe seeds (pre-enrichment cost saver) ───
        if si <= PHASE_ORDER.index("dedupe_seeds"):
            update_job(job_id, resume_from="dedupe_seeds", current_stage="dedupe_seeds")
            _check_stop(job_id)  # fast/uninterruptible phase — honour stop at its start
            print("\n🧹 Phase 2: Dedupe seeds (pre-enrichment)")
            seeds = seeds or []
            unique_seeds = dedupe_seeds(seeds)
            record_stage(job_id, "dedupe_seeds", unique_seeds)  # Workstream E — Phase 2 snapshot (unique seeds)
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
            if mode == "vendor":
                # Vendor mode: no tier classifier — build vendor rows (alias roll-up,
                # big-box + lumber flags). Every seed becomes a vendor record.
                included = _vendor_rows_from_seeds(unique_seeds, plan["state"], client_id, job_id)
            else:
                included = classify_seeds(unique_seeds, keywords, job_id)
            included = _tag_geo(included, plan["state"], mode, client_id)
            record_stage(job_id, "classify", included)  # Workstream E — Phase 3 snapshot (tiered + flagged)
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
            record_stage(job_id, "cap", rows)  # Workstream E — Phase 4 snapshot (capped set)
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
            dbpr_index = fetch_licenses_for_seeds_by_state(rows)  # FL→DBPR, TN→Nashville
            enrich_summary = enrich_and_insert_rows(
                rows, dbpr_index, job_id, should_stop=lambda: is_stop_requested(job_id),
                bbb_budget_usd=bbb_budget, apollo_budget_usd=apollo_budget,
            )  # raises on stop (nothing persisted until it finishes the row set)
            # Workstream E — Phase 5 snapshot: the enriched + saved set (the deliverable layer).
            record_stage(job_id, "enrich", rows)
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
        # Boundary stop: stops are now honoured only BETWEEN phases, after the
        # running phase has finished and checkpointed its output. So nothing is
        # discarded — resume_from points at the NEXT phase and its input is already
        # on disk. Resume continues from there with the saved (raw) data; the
        # expensive discovery + enrichment work is never re-paid.
        clear_job_stop(job_id)
        job = get_job(job_id) or {}
        update_job(job_id, status="paused", current_stage="paused", stages_progress=progress)
        print(f"⏸️  Pipeline PAUSED — job_id={job_id} "
              f"(resume_from={job.get('resume_from')}) — prior stage saved, resume continues from there")

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
