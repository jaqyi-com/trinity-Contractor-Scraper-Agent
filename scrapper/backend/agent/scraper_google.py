# scraper_google.py
# Outscraper Google Maps scraper — PRIMARY discovery source (PDF Section 2.1).
# Returns List[GoogleSeed] for one metro.

import os
from typing import List
from dotenv import load_dotenv

from agent.schema import GoogleSeed
from agent.db import get_active_keywords

load_dotenv()

OUTSCRAPER_API_KEY = os.getenv("OUTSCRAPER_API_KEY")

# Test/dev flag — when true, scrape_metro returns hardcoded SAMPLE_SEEDS
# instead of calling Outscraper. Lets you run the full pipeline (classify →
# enrich → dedupe → insert → web UI) without spending Outscraper credits.
USE_SAMPLE_DATA = os.getenv("USE_SAMPLE_DATA", "").lower() in ("1", "true", "yes")


# ──────────────────────────────────────────────────────────────
# Sample seeds for local testing (USE_SAMPLE_DATA=true).
# 5 Tampa businesses chosen to land in 5 different tiers after classification.
# ──────────────────────────────────────────────────────────────
SAMPLE_SEEDS = [
    # Real Tampa-area drywall contractors. Google-discoverable fields only
    # (name/address/phone/website/categories/services). `email` is left blank
    # on purpose so the Hunter/Apollo enrichment cascade has to fill it.
    GoogleSeed(
        place_id="real_talmadge_1",
        business_name="Talmadge Drywall (ICS, LLC)",
        city="Tampa",
        zip_code="33619",
        address="6101 Johns Rd, Tampa, FL 33634",
        phone="+18136356446",
        email=None,
        website="https://www.ics-fl.net",
        google_categories=["drywall_contractor"],
        services_listed=["drywall", "metal framing", "drywall repair", "new construction drywall"],
        description="Family drywall business with over 50 years in the Tampa drywall trade.",
        google_rating=4.7,
        google_review_count=38,
        social_profiles={},
    ),
    GoogleSeed(
        place_id="real_weststar_1",
        business_name="West Star Interiors Inc",
        city="Tampa",
        zip_code="33610",
        address="6810 E Adamo Dr, Tampa, FL 33619",
        phone="+18136261844",
        email=None,
        website="https://weststarinteriors.com",
        google_categories=["drywall_contractor"],
        services_listed=["commercial drywall", "metal framing", "stucco", "drywall installation"],
        description="Premier CFMF, drywall and stucco subcontractor in Tampa and Central Florida since 1990.",
        google_rating=4.4,
        google_review_count=21,
        social_profiles={},
    ),
    GoogleSeed(
        place_id="real_mader_1",
        business_name="Mader Southeast",
        city="Tampa",
        zip_code="33607",
        address="5101 W Cypress St, Tampa, FL 33607",
        phone="+14078778818",
        email=None,
        website="https://www.madersoutheast.com",
        google_categories=["drywall_contractor", "general_contractor"],
        services_listed=["commercial drywall", "interior build-outs", "metal framing", "drywall installation"],
        description="Leading commercial drywall contractor serving Orlando, Tampa, and Central Florida.",
        google_rating=4.6,
        google_review_count=44,
        social_profiles={},
    ),
    GoogleSeed(
        place_id="real_stuller_1",
        business_name="Stuller Drywall Inc",
        city="Tampa",
        zip_code="33612",
        address="Tampa Bay, FL",
        phone="+17274210255",
        email=None,
        website="https://stullerdrywall.com",
        google_categories=["drywall_contractor"],
        services_listed=["drywall", "sheetrock", "drywall finishing", "texturing"],
        description="Tampa Bay's drywall specialists.",
        google_rating=4.8,
        google_review_count=29,
        social_profiles={},
    ),
    GoogleSeed(
        place_id="real_raynor_1",
        business_name="Raynor Company Group",
        city="Tampa",
        zip_code="33602",
        address="Tampa Bay, FL",
        phone="+17275856391",
        email=None,
        website="https://theraynorgroup.com",
        google_categories=["general_contractor"],
        services_listed=["drywall", "general contractor", "construction services", "interior finishes"],
        description="Tampa Bay construction and drywall group, established 1957.",
        google_rating=4.5,
        google_review_count=33,
        social_profiles={},
    ),
    # Deliberate DUPLICATE of West Star (same phone, different name/place_id) —
    # used to verify Stage 5 dedupe merges by phone. Remove for production.
    GoogleSeed(
        place_id="real_weststar_DUP",
        business_name="West Star Interiors LLC",
        city="Tampa",
        zip_code="33610",
        address="6810 East Adamo Drive, Tampa, FL 33619",
        phone="+18136261844",
        email=None,
        website="https://weststarinteriors.com",
        google_categories=["drywall_contractor"],
        services_listed=["drywall", "metal framing"],
        description="Duplicate listing for dedupe testing.",
        google_rating=4.4,
        google_review_count=21,
        social_profiles={},
    ),
]


# ──────────────────────────────────────────────────────────────
# Static Outscraper search phrases (PDF Section 2.1).
# These are GOOGLE SEARCH PHRASES (what we type into Google Maps),
# NOT classifier keywords. Rarely edited — kept as Python constant.
# If you ever want user-editable queries, add a 'QUERY' tier to keywords table.
# ──────────────────────────────────────────────────────────────
DEFAULT_QUERIES = [
    "drywall contractor",
    "drywall repair",
    "drywall texturing",
    "sheetrock contractor",
    "plasterer",
    "popcorn ceiling",
    "general contractor",
    "painting contractor",
    "painter",
    "remodeling contractor",
    "home renovation",
    "handyman",
    "home repair",
]


def _derive_outscraper_filters() -> tuple[list[str], list[str]]:
    """
    Build Outscraper subtype include/exclude lists from the `keywords` DB table.

    Include = all active keywords from in-scope tiers (TIER_1_*, TIER_2_*, TIER_3_*).
    Exclude = all active keywords from EXCLUDE_HARD + EXCLUDE_SOLO tiers.

    This means: edit keywords in the UI → Outscraper filters auto-update on next run.
    No duplication between cities.yaml and DB.
    """
    keywords = get_active_keywords()
    include: list[str] = []
    exclude: list[str] = []
    in_scope_prefixes = ("TIER_1_", "TIER_2_", "TIER_3_")
    exclude_tiers = {"EXCLUDE_HARD", "EXCLUDE_SOLO"}

    for kw in keywords:
        if kw["tier"].startswith(in_scope_prefixes):
            include.append(kw["keyword"])
        elif kw["tier"] in exclude_tiers:
            exclude.append(kw["keyword"])

    return include, exclude


def scrape_metro(city: str, zips: List[str], queries: List[str] = None) -> List[GoogleSeed]:
    """
    For each (zip, query) tuple, call Outscraper and collect business listings.
    Apply subtype include/exclude filters derived from DB keywords.

    TODO: implement Outscraper SDK call.
    """
    # Sample/test mode — skip Outscraper entirely, return hardcoded seeds.
    if USE_SAMPLE_DATA:
        samples = [s for s in SAMPLE_SEEDS if s.city.lower() == city.lower()]
        print(f"🧪 [Google] SAMPLE MODE — returning {len(samples)} sample seeds for {city}")
        return samples

    queries = queries or DEFAULT_QUERIES
    include_subtypes, exclude_subtypes = _derive_outscraper_filters()

    print(f"🔍 [Google] city={city} zips={len(zips)} queries={len(queries)}")
    print(f"   subtype include ({len(include_subtypes)}): {include_subtypes[:5]}...")
    print(f"   subtype exclude ({len(exclude_subtypes)}): {exclude_subtypes[:5]}...")

    if not OUTSCRAPER_API_KEY:
        print("⚠️ OUTSCRAPER_API_KEY not set — returning empty list")
        return []

    seeds: List[GoogleSeed] = []
    # TODO: real Outscraper implementation
    # from outscraper import ApiClient
    # client = ApiClient(api_key=OUTSCRAPER_API_KEY)
    # for zip_code in zips:
    #     for q in queries:
    #         results = client.google_maps_search(
    #             query=f"{q}, {zip_code}",
    #             limit=500,
    #             enrichment=["emails_validator_service"],
    #             # subtype filters applied here
    #         )
    #         for r in results[0]:
    #             # Skip if subtype matches exclude or doesn't match include
    #             seeds.append(_to_google_seed(r, city))
    return seeds


def _to_google_seed(raw: dict, city: str) -> GoogleSeed:
    """Map Outscraper raw response → GoogleSeed."""
    return GoogleSeed(
        place_id=raw.get("place_id", ""),
        business_name=raw.get("name", ""),
        city=city,
        raw=raw,
    )
