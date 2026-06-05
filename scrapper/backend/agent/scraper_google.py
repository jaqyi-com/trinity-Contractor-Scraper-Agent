# scraper_google.py
# Google Maps discovery via the Apify actor (PDF Section 2.1 — "or Apify
# equivalent"). Apify is the sole discovery source; no separate Outscraper key.
# Returns List[GoogleSeed] for one metro.

import os
from typing import List
from dotenv import load_dotenv

from agent.schema import GoogleSeed
from utils.phone_normalizer import normalize_phone

load_dotenv()

APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN")

# Apify Google Maps actor — primary (only) discovery source.
APIFY_MAPS_ACTOR = "compass~crawler-google-places"
# Per-HTTP-call timeout (start/poll/fetch are all short calls now — NOT the whole
# scrape). The scrape itself runs async on Apify and can take many minutes.
APIFY_TIMEOUT = 60
APIFY_POLL_INTERVAL = 10                                  # seconds between status checks
APIFY_MAX_WAIT = int(os.getenv("APIFY_MAX_WAIT", "3600"))  # max wait per metro run (1h)

# Test/dev flag — when true, scrape_metro returns hardcoded SAMPLE_SEEDS instead
# of calling Apify. Lets you run the full pipeline (classify → enrich → dedupe →
# insert → web UI) without spending Apify credits.
USE_SAMPLE_DATA = os.getenv("USE_SAMPLE_DATA", "").lower() in ("1", "true", "yes")

# Production: NO per-metro cap — full-scale discovery (all queries run with
# maxCrawledPlacesPerSearch), meeting the spec's ≥2,000 businesses. Apify cost
# applies (~$50–75 per full 6-metro run), so keep APIFY_API_TOKEN funded.
# Set DISCOVERY_RESULT_CAP=<n> in the env for a cheap/fast test run (1 query,
# n places per metro); leave unset/blank for full scale.
_cap_env = os.getenv("DISCOVERY_RESULT_CAP", "").strip()
DISCOVERY_RESULT_CAP = int(_cap_env) if _cap_env.isdigit() else None


# ──────────────────────────────────────────────────────────────
# Sample seeds for local testing (USE_SAMPLE_DATA=true).
# 5 Tampa businesses chosen to land in 5 different tiers after classification.
# ──────────────────────────────────────────────────────────────
SAMPLE_SEEDS = [
    # Real Tampa-area drywall contractors. Google-discoverable fields only
    # (name/address/phone/website/categories/services). `email` is left blank
    # on purpose so the Apollo enrichment cascade has to fill it.
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
]


# ──────────────────────────────────────────────────────────────
# Google Maps search phrases fed to the Apify actor (searchStringsArray).
# These are SEARCH PHRASES, not classifier keywords. Rarely edited.
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


def scrape_metro(city: str, zips: List[str], queries: List[str] = None,
                 max_charge_usd: float = None) -> List[GoogleSeed]:
    """
    Discover businesses for one metro via the Apify Google Maps actor (the sole
    discovery source — no Outscraper key). Subtype include/exclude is enforced
    authoritatively by the Stage-3 classifier, so we don't re-filter here.
    `zips` is accepted for signature compatibility; the actor searches by city.
    """
    # Sample/test mode — skip live scraping entirely, return hardcoded seeds.
    if USE_SAMPLE_DATA:
        samples = [s for s in SAMPLE_SEEDS if s.city.lower() == city.lower()]
        print(f"🧪 [Google] SAMPLE MODE — returning {len(samples)} sample seeds for {city}")
        return samples

    if not APIFY_API_TOKEN:
        print("⚠️ [Google] APIFY_API_TOKEN not set — no discovery source available")
        return []

    queries = queries or DEFAULT_QUERIES
    cap = DISCOVERY_RESULT_CAP  # None = no cap (full scale)
    return _scrape_apify_maps(city, queries, cap, max_charge_usd)


def _scrape_apify_maps(city: str, queries: List[str], cap,
                       max_charge_usd: float = None) -> List[GoogleSeed]:
    """Discovery via the Apify Google Maps actor, ASYNC pattern: start the run,
    poll until it finishes, then read its dataset. The old run-sync endpoint has
    a ~300s server cap, which a full metro scrape (all queries × scrapeContacts)
    always blows past → 502 Bad Gateway / read-timeout. Async has no time limit.

    `max_charge_usd` (when set) is passed to Apify as maxTotalChargeUsd — a HARD
    dollar cap on this run that Apify enforces itself (the actor stops once it has
    charged that much). None = unlimited."""
    import requests
    import time

    search_strings = queries if cap is None else queries[:1]
    per_search = cap if cap is not None else 120
    payload = {
        "searchStringsArray": search_strings,
        "locationQuery": f"{city}, FL, USA",
        "maxCrawledPlacesPerSearch": per_search,
        "scrapeContacts": True,
        "language": "en",
    }
    base = "https://api.apify.com/v2"
    run_params = {"token": APIFY_API_TOKEN}
    if max_charge_usd and max_charge_usd > 0:
        run_params["maxTotalChargeUsd"] = max_charge_usd
        print(f"💰 [Google/Apify] {city}: maxTotalChargeUsd=${max_charge_usd:.4f} (hard cap)")

    # 1. Start the run asynchronously — returns immediately with run + dataset ids.
    try:
        resp = requests.post(
            f"{base}/acts/{APIFY_MAPS_ACTOR}/runs",
            params=run_params, json=payload, timeout=APIFY_TIMEOUT,
        )
        resp.raise_for_status()
        run = resp.json()["data"]
        run_id, dataset_id = run["id"], run["defaultDatasetId"]
    except Exception as e:
        print(f"⚠️ [Google/Apify] {city}: run start failed: {e}")
        return []

    # 2. Poll the run until it reaches a terminal state (or we hit the wait cap).
    status, waited = None, 0
    while waited < APIFY_MAX_WAIT:
        time.sleep(APIFY_POLL_INTERVAL)
        waited += APIFY_POLL_INTERVAL
        try:
            s = requests.get(
                f"{base}/actor-runs/{run_id}",
                params={"token": APIFY_API_TOKEN}, timeout=APIFY_TIMEOUT,
            )
            s.raise_for_status()
            status = s.json()["data"]["status"]
        except Exception as e:
            print(f"⚠️ [Google/Apify] {city}: poll error (continuing): {e}")
            continue
        if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT", "TIMING-OUT"):
            break
    if status != "SUCCEEDED":
        print(f"⚠️ [Google/Apify] {city}: run status={status} after {waited}s "
              f"— reading whatever was collected")

    # 3. Read the dataset (paginated — a full metro can be >1k items).
    items: list = []
    offset, page = 0, 1000
    while True:
        try:
            r = requests.get(
                f"{base}/datasets/{dataset_id}/items",
                params={"token": APIFY_API_TOKEN, "offset": offset,
                        "limit": page, "clean": "true"},
                timeout=120,
            )
            r.raise_for_status()
            batch = r.json()
        except Exception as e:
            print(f"⚠️ [Google/Apify] {city}: dataset fetch error: {e}")
            break
        if not isinstance(batch, list) or not batch:
            break
        items.extend(batch)
        if len(batch) < page:
            break
        offset += page

    seeds: List[GoogleSeed] = []
    seen: set = set()
    for r in items:
        if cap is not None and len(seeds) >= cap:
            break
        pid = r.get("placeId")
        if pid and pid in seen:
            continue
        seeds.append(_apify_place_to_seed(r, city))
        if pid:
            seen.add(pid)

    print(f"🔍 [Google/Apify] {city}: {len(seeds)} seeds")
    return seeds


def _apify_place_to_seed(raw: dict, city: str) -> GoogleSeed:
    """Map a compass/crawler-google-places result → GoogleSeed."""
    cats: List[str] = []
    if raw.get("categoryName"):
        cats.append(raw["categoryName"])
    if isinstance(raw.get("categories"), list):
        cats.extend(c for c in raw["categories"] if c)
    seen, ucats = set(), []
    for c in cats:
        if c and c.lower() not in seen:
            seen.add(c.lower())
            ucats.append(c)

    emails = raw.get("emails")
    email = emails[0] if isinstance(emails, list) and emails else (raw.get("email") or None)

    social = {}
    for src, dest in (("facebooks", "facebook"), ("instagrams", "instagram"),
                      ("linkedIns", "linkedin"), ("twitters", "twitter")):
        v = raw.get(src)
        if isinstance(v, list) and v:
            social[dest] = v[0]
        elif isinstance(v, str) and v:
            social[dest] = v

    phone_raw = raw.get("phoneUnformatted") or raw.get("phone")
    return GoogleSeed(
        place_id=raw.get("placeId") or "",
        business_name=raw.get("title") or "",
        city=raw.get("city") or city,
        zip_code=raw.get("postalCode") or None,
        address=raw.get("address") or None,
        phone=(normalize_phone(phone_raw) or phone_raw) if phone_raw else None,
        email=email,
        website=raw.get("website") or None,
        google_categories=ucats,
        services_listed=[],
        description=raw.get("description") or "",
        google_rating=raw.get("totalScore"),
        google_review_count=raw.get("reviewsCount"),
        social_profiles=social,
        raw=raw,
    )
