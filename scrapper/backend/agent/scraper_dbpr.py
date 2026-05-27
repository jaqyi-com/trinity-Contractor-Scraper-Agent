# scraper_dbpr.py
# Florida DBPR license lookup — PDF Section 2.2.
# Uses the Apify "DBPR Florida License Verification" actor (ws_tony) instead of
# raw Playwright: it handles the ASP postbacks, returns structured records, and
# runs fine anywhere (no Chromium bundle needed).

import os
from typing import List

import requests
from dotenv import load_dotenv

from agent.schema import DBPRLicense, GoogleSeed

load_dotenv()

APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN")

DBPR_ACTOR = "ws_tony~dbpr-florida-license-verification"
HTTP_TIMEOUT = 280


# Static Florida DBPR license categories — PDF Section 2.2 (FL-law fixed).
LICENSE_CATEGORIES = [
    "Gypsum Drywall Contractor",
    "Certified General Contractor",
    "Certified Building Contractor",
    "Certified Residential Contractor",
    "Registered General Contractor",
    "Registered Building Contractor",
    "Registered Residential Contractor",
    "Painting Contractor",
]


def _to_dbpr_license(item: dict) -> DBPRLicense:
    addr = item.get("main_address") or {}
    dba = item.get("dba_names") or []
    return DBPRLicense(
        license_number=item.get("license_number") or "",
        license_category=item.get("license_type") or "",
        licensee_name=item.get("name") or item.get("primary_name") or "",
        dba_name=dba[0] if dba else None,
        status=item.get("status") or "",
        city=addr.get("city"),
        zip_code=addr.get("postal_code"),
        phone=item.get("phone"),
        original_issue_date=item.get("licensure_date"),
        raw=item,
    )


def fetch_licenses_for_seeds(seeds: List[GoogleSeed]) -> List[DBPRLicense]:
    """
    Look up DBPR licenses for the businesses discovered in a metro.
    Searches the DBPR database by each unique business name (orgName) in one
    Apify run, then returns all matching license records for downstream matching.
    """
    if not APIFY_API_TOKEN or not seeds:
        return []

    names = sorted({s.business_name.strip() for s in seeds if s.business_name})
    if not names:
        return []

    payload = {
        "licenseeNames": [{"orgName": n} for n in names],
        "enrichmentLevel": "basic",
        "includeExpired": True,        # we tag inactive too, not just active
        "maxResultsPerSearch": 10,
    }

    print(f"🏛️  [DBPR] Apify lookup for {len(names)} business names")
    try:
        resp = requests.post(
            f"https://api.apify.com/v2/acts/{DBPR_ACTOR}/run-sync-get-dataset-items",
            params={"token": APIFY_API_TOKEN},
            json=payload,
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        items = resp.json()
    except Exception as e:
        print(f"⚠️  DBPR actor error: {e}")
        return []

    if not isinstance(items, list):
        return []

    return [_to_dbpr_license(it) for it in items if it.get("license_number")]


def fetch_licenses_for_metro(city: str) -> List[DBPRLicense]:
    """Deprecated per-metro entrypoint — kept for compatibility. Prefer
    fetch_licenses_for_seeds(seeds), which searches by discovered business name."""
    return []
