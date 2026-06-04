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
from agent.matcher import match_license_by_name
from agent.scraper_bbb import enrich_bbb
from agent.enrichment import enrich_email, apollo_company
from utils.url_normalizer import extract_domain
from agent.db import insert_contractor, insert_classification_logs
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


# ──────────────────────────────────────────────────────────────
# Phase 1 — Discovery (one metro). Returns raw seeds; NO enrichment yet.
# ──────────────────────────────────────────────────────────────
def discover_metro(city, job_id: str) -> List[GoogleSeed]:
    """Google Maps discovery for ONE city. Writes the stage-1 audit JSONL."""
    city_name = city["name"] if isinstance(city, dict) else city.name
    zips = city["zips"] if isinstance(city, dict) else city.zips

    print(f"🔍 [{city_name}] Stage 1: Google Discovery")
    seeds = scrape_metro(city_name, zips)  # queries default to DEFAULT_QUERIES
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
def _enrich_one(row: ContractorRow) -> None:
    """All external enrichment for a single contractor row (BBB + Apollo)."""
    # BBB rating / accreditation / years
    try:
        bbb = enrich_bbb(row)
        if bbb.rating:
            row.bbb_rating = bbb.rating
            if "bbb" not in row.sources:
                row.sources.append("bbb")
        row.bbb_accredited = bbb.accredited
        if bbb.years_in_business:
            row.years_in_business = bbb.years_in_business
    except Exception as e:
        print(f"⚠️  BBB error for {row.business_name}: {e}")

    # Apollo: email/owner/linkedin + company facts
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


def enrich_and_insert_rows(rows: List[ContractorRow], dbpr_index: list, job_id: str) -> dict:
    """License-match → parallel BBB/Apollo enrich → UPSERT each row to the DB."""
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

    # ─── Enrichment (BBB + Apollo) — parallelized ───
    print(f"💎📧 Enrichment — {len(rows)} rows × {ENRICH_WORKERS} workers")
    with ThreadPoolExecutor(max_workers=ENRICH_WORKERS) as ex:
        list(ex.map(_enrich_one, rows))

    # ─── Persist — versioned save (new / changed-version / skip handled in db) ───
    for row in rows:
        try:
            insert_contractor(row.model_dump(mode="json"))
            summary["saved"] += 1
            print(f"💾 Saved: {row.business_name} ({row.tier})")
        except Exception as e:
            print(f"❌ DB insert failed for {row.business_name}: {e}")
            summary["errors"].append({"stage": "insert", "name": row.business_name, "error": str(e)})

    return summary
