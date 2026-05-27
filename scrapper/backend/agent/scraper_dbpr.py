# scraper_dbpr.py
# Florida DBPR license lookup — PDF Section 2.2.
#
# Primary (free): query the local dbpr_licenses table, loaded weekly from the
# official DBPR bulk CSV (see agent/dbpr_loader.py).
# Fallback (paid): for business names not found in the bulk table, call the
# Apify "DBPR Florida License Verification" actor. This recovers Null&Void /
# delinquent records the bulk file omits, and businesses whose licence sits
# under a name the bulk extract doesn't expose.

import os
from typing import List

import requests
from dotenv import load_dotenv

from agent.schema import DBPRLicense, GoogleSeed
from agent.db import query_dbpr_by_names
from utils.name_normalizer import normalize_name

load_dotenv()

APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN")

# The bulk DBPR table (free, fast) is primary. The paid Apify per-metro fallback
# (for names absent from the bulk file) is slow + credit-hungry — toggle off for
# fast/low-cost runs. Names with no bulk match then stay "unlicensed".
ENABLE_DBPR_FALLBACK = os.getenv("ENABLE_DBPR_FALLBACK", "true").lower() in ("1", "true", "yes")

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


# ──────────────────────────────────────────────────────────────
# Bulk table → DBPRLicense
# ──────────────────────────────────────────────────────────────
def _bulk_row_to_license(r: dict) -> DBPRLicense:
    # Hand the matcher a status string it maps correctly (see matcher
    # ._license_status_from_dbpr, which checks 'inactive' before 'active').
    status_str = "Current, Inactive" if r.get("license_status") == "licensed_inactive" else "Current, Active"
    return DBPRLicense(
        license_number=r.get("license_number") or "",
        license_category=r.get("occupation_code") or "",
        licensee_name=r.get("licensee_name") or "",
        dba_name=r.get("dba_name"),
        status=status_str,
        city=r.get("city"),
        zip_code=r.get("zip_code"),
        phone=None,
        original_issue_date=r.get("original_issue_date"),
        raw=r,
    )


# ──────────────────────────────────────────────────────────────
# Apify fallback → DBPRLicense
# ──────────────────────────────────────────────────────────────
def _apify_row_to_license(item: dict) -> DBPRLicense:
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


def _apify_lookup(names: List[str]) -> List[DBPRLicense]:
    """Paid fallback — DBPR verification actor, searched by business orgName."""
    if not APIFY_API_TOKEN or not names:
        return []

    payload = {
        "licenseeNames": [{"orgName": n} for n in names],
        "enrichmentLevel": "basic",
        "includeExpired": True,
        "maxResultsPerSearch": 10,
    }
    print(f"🏛️  [DBPR] Apify fallback for {len(names)} unmatched names")
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
        print(f"⚠️  DBPR Apify fallback error: {e}")
        return []

    if not isinstance(items, list):
        return []
    return [_apify_row_to_license(it) for it in items if it.get("license_number")]


def fetch_licenses_for_seeds(seeds: List[GoogleSeed]) -> List[DBPRLicense]:
    """
    Resolve DBPR licenses for the businesses discovered in a metro.
    1. Free: match unique business names against the local bulk table.
    2. Paid fallback: Apify verifier for names with zero bulk matches.
    """
    if not seeds:
        return []

    names = sorted({s.business_name.strip() for s in seeds if s.business_name})
    if not names:
        return []

    normalized = [normalize_name(n) for n in names]
    bulk_rows = query_dbpr_by_names(normalized)
    licenses = [_bulk_row_to_license(r) for r in bulk_rows]

    matched_norms = {normalize_name(lic.licensee_name) for lic in licenses}
    matched_norms |= {normalize_name(lic.dba_name) for lic in licenses if lic.dba_name}
    unmatched = [n for n in names if normalize_name(n) not in matched_norms]

    if unmatched and ENABLE_DBPR_FALLBACK:
        print(f"🏛️  [DBPR] bulk matched {len(names) - len(unmatched)}/{len(names)} names; {len(unmatched)} to Apify fallback")
        licenses.extend(_apify_lookup(unmatched))
    else:
        print(f"🏛️  [DBPR] bulk matched {len(names) - len(unmatched)}/{len(names)} names; fallback {'off' if not ENABLE_DBPR_FALLBACK else 'n/a'}")

    return licenses
