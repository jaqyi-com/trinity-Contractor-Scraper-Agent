# scraper_bbb.py
# BBB enrichment via Apify BBB actor — PDF Section 2.3.
# BBB blocks raw scrapers, so we use an existing actor.

import os
import re
from datetime import datetime

import requests
from dotenv import load_dotenv

from agent.schema import ContractorRow, BBBEnrichment

load_dotenv()

APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN")

# BBB enrichment (PDF 2.3). ON by default so production never silently drops
# BBB data. It's slow (one Apify actor run per business, ~45s, pay-per-event)
# but runs parallelized (processor.ENRICH_WORKERS). Set ENABLE_BBB=false to skip.
ENABLE_BBB = os.getenv("ENABLE_BBB", "true").lower() in ("1", "true", "yes")

# Pay-per-event actor: ~$0.10 per run start + $0.02 per business profile.
BBB_ACTOR = "alizarin_refrigerator-owner~bbb-scraper"
HTTP_TIMEOUT = 180


def _years_from(item: dict) -> int | None:
    """Derive years in business from yearsInBusiness or a start/accredited year."""
    y = item.get("yearsInBusiness")
    if isinstance(y, int):
        # Some BBB records put a start YEAR (e.g. 2013) in this field, not a count.
        if y > 1900:
            return max(0, datetime.utcnow().year - y)
        return y
    for key in ("businessStarted", "accreditedSince"):
        val = item.get(key)
        if val:
            m = re.search(r"(19|20)\d{2}", str(val))
            if m:
                return max(0, datetime.utcnow().year - int(m.group()))
    return None


def enrich_bbb(row: ContractorRow) -> BBBEnrichment:
    """
    Look up BBB rating + accreditation + years in business for one contractor
    via the Apify BBB actor (search by business name + location).
    """
    if not ENABLE_BBB:
        return BBBEnrichment()
    if not APIFY_API_TOKEN or not row.business_name:
        return BBBEnrichment()

    location = ", ".join(p for p in [row.city, (getattr(row, "state", None) or "FL")] if p)
    payload = {
        "scrapeType": "business_profile",
        "businessName": row.business_name,
        "location": location,
        "includeComplaints": False,
        "includeReviews": False,
        "demoMode": False,
        "maxResults": 1,
    }

    try:
        resp = requests.post(
            f"https://api.apify.com/v2/acts/{BBB_ACTOR}/run-sync-get-dataset-items",
            params={"token": APIFY_API_TOKEN},
            json=payload,
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        items = resp.json()
    except Exception as e:
        print(f"⚠️  BBB actor error for {row.business_name}: {e}")
        return BBBEnrichment()

    if not isinstance(items, list) or not items:
        return BBBEnrichment()

    item = items[0]
    # BBB category can arrive as a list ("categories") or a single string ("category").
    cats = item.get("categories") or item.get("category") or []
    if isinstance(cats, str):
        cats = [cats]
    return BBBEnrichment(
        bbb_id=item.get("bbbUrl"),
        rating=item.get("rating"),
        accredited=bool(item.get("accredited")),
        years_in_business=_years_from(item),
        out_of_business=bool(item.get("outOfBusiness", False)),
        categories=[str(c) for c in cats if c],
    )
