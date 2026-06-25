# processor.py
# Stage workers, split so the pipeline can run them in PHASES across all metros
# (discover everything → dedupe → classify → CAP → enrich) instead of doing the
# full chain per metro. The cap + the pre-enrichment dedupe both need the global
# seed set, so enrichment (the only paid-per-row stage) runs last, on survivors.

import os
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import List

from agent.scraper_google import scrape_metro
from agent.classifier import classify
from agent.lumber import check_lumber
from agent.matcher import match_license_by_name
from agent.scraper_bbb import enrich_bbb
from agent.enrichment import enrich_email, apollo_company
from utils.url_normalizer import extract_domain
from agent.db import insert_contractor, insert_classification_logs, record_source
from agent.storage import write_stage_jsonl
from agent.schema import ContractorRow, GoogleSeed

# Per-row enrichment (BBB + Apollo) is I/O-bound (HTTP/actor calls), so rows run
# concurrently. Each thread mutates only its own row and touches no DB → safe.
#
# ⚠️ Concurrency semantics CHANGED with the phased pipeline: enrichment is now a
# SINGLE global pool, so ENRICH_WORKERS == peak concurrent Apify enrichment runs.
# (Previously each of METRO_WORKERS metro threads had its own pool, so real peak
# was METRO_WORKERS × ENRICH_WORKERS.) Set this to your Apify plan's concurrency
# limit — too low and a 5k-row run crawls (BBB ≈ 45s/row, so 5000/W × 45s).
ENRICH_WORKERS = int(os.getenv("ENRICH_WORKERS", "18"))

# Per-unit Apify/Apollo costs used to convert a USD budget → a row-count cap.
# BBB is a per-business Apify run: $0.10 actor-start + $0.02 business profile
# (from the actor's published PAY_PER_EVENT pricing) ≈ $0.12/business.
# Apollo has no Apify-style per-call price (credit/subscription based), so we use
# a configurable estimate per enriched row; override via APOLLO_COST_PER_ROW.
BBB_COST_PER_BUSINESS = float(os.getenv("BBB_COST_PER_BUSINESS", "0.12"))
APOLLO_COST_PER_ROW = float(os.getenv("APOLLO_COST_PER_ROW", "0.05"))


def _budget_to_count(budget_usd, per_unit_cost: float):
    """USD budget → how many rows we can afford. None budget = unlimited (None)."""
    if budget_usd is None or per_unit_cost <= 0:
        return None
    return int(budget_usd // per_unit_cost)


class PipelineStopRequested(Exception):
    """Raised mid-stage when a stop has been requested, so the pipeline bails out
    immediately and DISCARDS the in-progress stage's partial work. Defined here
    (not in pipeline.py) so both the orchestrator and stage workers can raise it
    without a circular import. The orchestrator sets resume_from to the in-progress
    stage BEFORE the work starts, so resume re-runs this stage from scratch on the
    last completed stage's checkpoint."""


# ──────────────────────────────────────────────────────────────
# Phase 1 — Discovery (one metro). Returns raw seeds; NO enrichment yet.
# ──────────────────────────────────────────────────────────────
def discover_metro(city, job_id: str, max_charge_usd: float = None,
                   state: str = "FL", queries: list = None) -> List[GoogleSeed]:
    """Google Maps discovery for ONE city. Writes the stage-1 audit JSONL.
    `max_charge_usd` is this metro's slice of the run-wide discovery budget.
    `state` (FL|TN) and `queries` (None=contractor defaults, or VENDOR_QUERIES for
    vendor mode) come from the run plan; defaults preserve FL-contractor behaviour."""
    city_name = city["name"] if isinstance(city, dict) else city.name
    zips = city["zips"] if isinstance(city, dict) else city.zips

    print(f"🔍 [{city_name}, {state}] Stage 1: Google Discovery")
    seeds = scrape_metro(city_name, zips, queries=queries, max_charge_usd=max_charge_usd, state=state)
    write_stage_jsonl(job_id, "stage1_google", city_name, seeds)
    print(f"🔍 [{city_name}] discovered {len(seeds)} seeds")
    return seeds


# ──────────────────────────────────────────────────────────────
# Phase 3 — Classify (cheap, pure Python). Logs EVERY decision; returns the
# INCLUDED rows only (built from seed + decision).
# ──────────────────────────────────────────────────────────────
def classify_seeds(seeds: List[GoogleSeed], keywords: list, job_id: str) -> List[ContractorRow]:
    rows: List[ContractorRow] = []
    log_records: list = []
    for seed in seeds:
        try:
            decision = classify(seed, keywords)
            log_records.append({
                "job_id": job_id,
                "business_name": seed.business_name,
                "place_id": seed.place_id,
                "decision": decision.decision,
                "assigned_tier": decision.assigned_tier,
                "matched_keywords": [m.model_dump() for m in decision.matched_keywords],
                "exclusion_keywords": [m.model_dump() for m in decision.exclusion_keywords],
                "classifier_text": decision.classifier_text,
                "reason": decision.reason,
            })
            if decision.decision != "INCLUDED":
                continue
            place_ids = sorted({pid for pid in ([seed.place_id] + (seed.merged_place_ids or [])) if pid})
            # Lumber exclusion (Workstream D) — flag, don't delete: the row is kept,
            # the deliverable view filters flagged rows out later.
            excluded_reason = check_lumber({
                "business_name": seed.business_name,
                "description": seed.description,
                "google_categories": seed.google_categories,
            })
            rows.append(ContractorRow(
                business_name=seed.business_name,
                city=seed.city,
                zip_code=seed.zip_code,
                address=seed.address,
                phone=seed.phone,
                email=seed.email,
                website=seed.website,
                google_categories=seed.google_categories,
                services_listed=seed.services_listed,
                google_rating=seed.google_rating,
                google_review_count=seed.google_review_count,
                social_profiles=seed.social_profiles,
                place_ids=place_ids,
                sources=["google"],
                tier=decision.assigned_tier,
                specialty_keywords=[m.keyword for m in decision.matched_keywords],
                excluded_reason=excluded_reason,
                job_id=job_id,
            ))
        except Exception as e:
            print(f"⚠️  Classify error for {seed.business_name}: {e}")

    # Audit log: one bulk insert instead of thousands of per-seed round-trips.
    insert_classification_logs(log_records)
    print(f"🏷️  Classified {len(seeds)} seeds → {len(rows)} included ({len(log_records)} logged)")
    return rows


# ──────────────────────────────────────────────────────────────
# Phase 5 — License match + enrichment + persist (the only paid-per-row stage).
# Runs on the already-deduped, already-capped row set.
# ──────────────────────────────────────────────────────────────
def _enrich_one(task) -> None:
    """All external enrichment for a single contractor row (BBB + Apollo).
    `task` = (row, do_bbb, do_apollo) — the do_* flags let a per-service USD budget
    skip the paid call on rows beyond the budget's row-count cap."""
    row, do_bbb, do_apollo = task
    # BBB rating / accreditation / years
    if do_bbb:
        try:
            bbb = enrich_bbb(row)
            if bbb.rating:
                row.bbb_rating = bbb.rating
                if "bbb" not in row.sources:
                    row.sources.append("bbb")
            row.bbb_accredited = bbb.accredited
            if bbb.years_in_business:
                row.years_in_business = bbb.years_in_business
            # Lumber Layer 1 (BBB category): only known after enrichment, so re-check
            # here against the BBB categories. Flag, don't delete; don't overwrite.
            if bbb.categories and not row.excluded_reason:
                reason = check_lumber({
                    "business_name": row.business_name,
                    "google_categories": list(row.google_categories or []) + list(bbb.categories),
                })
                if reason:
                    row.excluded_reason = reason.replace("lumber:category", "lumber:bbb_category")
        except Exception as e:
            print(f"⚠️  BBB error for {row.business_name}: {e}")

    # Apollo: email/owner/linkedin + company facts
    if not do_apollo:
        return
    try:
        if not row.email:
            result = enrich_email(row)
            if result.email:
                row.email = result.email
            if result.owner_name:
                row.owner_name = result.owner_name
            if result.linkedin_url:
                row.social_profiles = {**(row.social_profiles or {}), "linkedin": result.linkedin_url}
            for s in result.sources:
                if s not in row.sources:
                    row.sources.append(s)

        domain = extract_domain(row.website) if row.website else None
        if domain:
            company = apollo_company(domain)
            if company:
                if company.get("years_in_business") and not row.years_in_business:
                    row.years_in_business = company["years_in_business"]
                if company.get("phone") and not row.phone:
                    row.phone = company["phone"]
                if company.get("linkedin_url") and "linkedin" not in (row.social_profiles or {}):
                    row.social_profiles = {**(row.social_profiles or {}), "linkedin": company["linkedin_url"]}
                if "apollo" not in row.sources:
                    row.sources.append("apollo")
    except Exception as e:
        print(f"⚠️  Apollo enrichment error for {row.business_name}: {e}")


def enrich_and_insert_rows(rows: List[ContractorRow], dbpr_index: list, job_id: str,
                           should_stop=None, bbb_budget_usd=None,
                           apollo_budget_usd=None, target_tab: str = "contractors") -> dict:
    """License-match → parallel BBB/Apollo enrich → UPSERT each row to the DB.

    `should_stop` (optional callable) is polled between enrichment waves so a stop
    request bails promptly. Nothing is persisted until the insert loop at the end,
    so bailing mid-enrich discards the whole stage cleanly — resume re-runs it from
    scratch. A single in-flight wave (≈ENRICH_WORKERS rows) can't be torn out, so
    worst-case latency after a stop ≈ one BBB call (~45s)."""
    summary = {"saved": 0, "errors": []}
    if not rows:
        return summary

    # ─── License match (name-based, free) ───
    print(f"🔗 License match — {len(rows)} rows")
    for row in rows:
        try:
            match = match_license_by_name(row, dbpr_index)
            if match:
                row.license_status = match.status
                row.license_numbers = match.numbers
                row.license_categories = match.categories
                if "dbpr" not in row.sources:
                    row.sources.append("dbpr")
            else:
                row.license_status = "unlicensed"
        except Exception as e:
            print(f"⚠️  License match error: {e}")

    # NOTE: enrichment is NOT interrupted mid-stage on stop. Once Phase 5 starts we
    # let it FINISH (license-match → enrich → persist) so partially-enriched rows
    # are never thrown away and the paid BBB/Apollo calls aren't wasted on a re-run.
    # A stop requested during enrich is honoured at the NEXT phase boundary
    # (dedupe_final), by which point every row is already persisted. `should_stop`
    # is kept for signature compatibility but intentionally not polled here.

    # ─── Per-service USD budgets → row-count caps (None = unlimited). Rows are
    # already ranked strongest-first by the cap stage, so the budget spends on the
    # best leads and skips the paid call on the tail. ───
    max_bbb = _budget_to_count(bbb_budget_usd, BBB_COST_PER_BUSINESS)
    max_apollo = _budget_to_count(apollo_budget_usd, APOLLO_COST_PER_ROW)
    if max_bbb is not None:
        print(f"💰 BBB budget ${bbb_budget_usd} ÷ ${BBB_COST_PER_BUSINESS}/biz "
              f"→ BBB on {min(max_bbb, len(rows))}/{len(rows)} rows "
              f"(skipping {max(0, len(rows) - max_bbb)})")
    if max_apollo is not None:
        print(f"💰 Apollo budget ${apollo_budget_usd} ÷ ${APOLLO_COST_PER_ROW}/row "
              f"→ Apollo on {min(max_apollo, len(rows))}/{len(rows)} rows "
              f"(skipping {max(0, len(rows) - max_apollo)})")

    tasks = [
        (row,
         max_bbb is None or i < max_bbb,
         max_apollo is None or i < max_apollo)
        for i, row in enumerate(rows)
    ]

    # ─── Enrichment (BBB + Apollo) — parallelized. Runs to completion (no
    # mid-stage stop): the stage finishes, then persists, then the pipeline pauses
    # at the next boundary if a stop is pending. ───
    print(f"💎📧 Enrichment — {len(rows)} rows × {ENRICH_WORKERS} workers")
    with ThreadPoolExecutor(max_workers=ENRICH_WORKERS) as ex:
        list(ex.map(_enrich_one, tasks))

    # ─── Persist — versioned save (new / changed-version / skip handled in db) ───
    for row in rows:
        rec = row.model_dump(mode="json")
        try:
            insert_contractor(rec, tab=target_tab)   # vendors → 'vendors' tab, kept separate
            summary["saved"] += 1
            print(f"💾 Saved [{target_tab}]: {row.business_name} ({row.tier or row.vendor_type})")
        except Exception as e:
            print(f"❌ DB insert failed for {row.business_name}: {e}")
            summary["errors"].append({"stage": "insert", "name": row.business_name, "error": str(e)})
            continue
        # Workstream E — raw/provenance layer: one immutable source_records row per
        # source this business came from (linked by canonical_entity_id). Additive —
        # the versioned contractors save above is unchanged; never blocks the save.
        try:
            for src in (rec.get("sources") or [None]):
                record_source(rec, src or "pipeline", run_id=job_id)
        except Exception as e:
            print(f"⚠️  source_records log failed for {row.business_name}: {e}")

    return summary
