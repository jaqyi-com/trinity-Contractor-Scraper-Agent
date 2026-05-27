# processor.py
# Per-metro processor — chains all stages for ONE city.
# Production scraper pattern: pipeline.py loops over inputs, processor.py does work per input.

import os
import traceback
from typing import Any
from concurrent.futures import ThreadPoolExecutor

from agent.scraper_google import scrape_metro
from agent.scraper_dbpr import fetch_licenses_for_seeds
from agent.classifier import classify
from agent.classification_logger import log_decision
from agent.matcher import match_license_by_name
from agent.scraper_bbb import enrich_bbb
from agent.enrichment import enrich_email, apollo_company
from utils.url_normalizer import extract_domain
from agent.db import insert_contractor, get_active_keywords
from agent.storage import write_stage_jsonl
from agent.schema import ContractorRow

# Per-row enrichment (BBB + Apollo) is I/O-bound (HTTP/actor calls), so we run
# rows concurrently instead of one-at-a-time. Each thread mutates only its own
# row and touches no DB, so this is safe. Tune with ENRICH_WORKERS.
ENRICH_WORKERS = int(os.getenv("ENRICH_WORKERS", "8"))


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


def process_metro(city, job_id: str) -> dict:
    """
    Run all 8 stages for ONE city.
    `city` is the YAML dict with .name + .zips. Queries come from scraper_google.DEFAULT_QUERIES.
    Returns a summary dict.
    """
    city_name = city["name"] if isinstance(city, dict) else city.name
    zips = city["zips"] if isinstance(city, dict) else city.zips

    summary = {
        "city": city_name,
        "seeds": 0,
        "included": 0,
        "excluded": 0,
        "saved": 0,
        "errors": [],
    }

    try:
        # ─── Stage 1: Google discovery ───────────────────
        print(f"\n🔍 [{city_name}] Stage 1: Google Discovery")
        seeds = scrape_metro(city_name, zips)  # queries default to DEFAULT_QUERIES
        write_stage_jsonl(job_id, "stage1_google", city_name, seeds)
        summary["seeds"] = len(seeds)

        # ─── Stage 2: DBPR licenses ──────────────────────
        print(f"🏛️  [{city_name}] Stage 2: DBPR Pull")
        dbpr_index = fetch_licenses_for_seeds(seeds)
        write_stage_jsonl(job_id, "stage2_dbpr", city_name, dbpr_index)

        # ─── Stage 3: Classify + audit log ──────────────
        print(f"🏷️  [{city_name}] Stage 3: Classify + Audit Log")
        keywords = get_active_keywords()
        classified: list = []
        for seed in seeds:
            try:
                decision = classify(seed, keywords)
                log_decision(job_id, seed, decision)
                if decision.decision == "INCLUDED":
                    summary["included"] += 1
                    # Build base ContractorRow from seed + decision
                    row = ContractorRow(
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
                        place_ids=[seed.place_id] if seed.place_id else [],
                        sources=["google"],
                        tier=decision.assigned_tier,
                        specialty_keywords=[m.keyword for m in decision.matched_keywords],
                        job_id=job_id,
                    )
                    classified.append(row)
                else:
                    summary["excluded"] += 1
            except Exception as e:
                print(f"⚠️  Classify error for {seed.business_name}: {e}")
                summary["errors"].append({"stage": "classify", "name": seed.business_name, "error": str(e)})

        write_stage_jsonl(job_id, "stage3_classified", city_name, classified)

        # ─── Stage 4: License match ─────────────────────
        print(f"🔗 [{city_name}] Stage 4: License Match")
        for row in classified:
            try:
                # ContractorRow + GoogleSeed both expose .business_name, so the
                # name-based matcher works on the row directly.
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

        # ─── Stage 6+7: Enrichment (BBB + Apollo) — parallelized ────
        print(f"💎📧 [{city_name}] Stage 6+7: Enrichment — {len(classified)} rows × {ENRICH_WORKERS} workers")
        if classified:
            with ThreadPoolExecutor(max_workers=ENRICH_WORKERS) as ex:
                list(ex.map(_enrich_one, classified))

        # ─── Persist to DB (per-metro, before global dedupe) ────────
        for row in classified:
            try:
                insert_contractor(row.model_dump(mode="json"))
                summary["saved"] += 1
                print(f"💾 Saved: {row.business_name} ({row.tier})")
            except Exception as e:
                print(f"❌ DB insert failed for {row.business_name}: {e}")
                summary["errors"].append({"stage": "insert", "name": row.business_name, "error": str(e)})

        print(f"🎯 Done {city_name}: {summary['saved']} saved / {summary['included']} included / {summary['excluded']} excluded")
        return summary

    except Exception as e:
        print(f"❌ Metro {city_name} failed: {e}")
        traceback.print_exc()
        summary["errors"].append({"stage": "metro", "error": str(e)})
        return summary
