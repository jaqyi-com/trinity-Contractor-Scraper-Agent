# scraper_tn_license.py
# Tennessee contractor-license ENRICHMENT — the TN counterpart of dbpr_loader.
#
# TN publishes no Florida-style statewide bulk CSV, so we use Nashville's free
# "Registered Professional Contractors and Licenses" open dataset (ArcGIS Hub
# Feature Service). License data is VALIDATION/ENRICHMENT only — discovery still
# relies on Google + BBB + keywords; never the primary engine.
#
# Same contract as dbpr_loader.query_by_normalized_names(names) → match records,
# so the pipeline can branch by state (FL → DBPR, TN → this) with one interface.
#
# Note (per spec): license records are keyed to a trade CLASSIFICATION (Prof__Type,
# e.g. "General Contractor License"), NOT the word "drywall" — no classification in
# the dataset literally says "drywall"; drywall/GC work is performed under the
# building / general / carpentry / painting / masonry classifications. So we filter
# license matches by CLASSIFICATION, not keyword (see RELEVANT_CLASSIFICATIONS): a
# business whose only TN license is for an unrelated trade (plumbing, electrical,
# HVAC, roofing, …) is NOT treated as a validated contractor for our ICP. The
# dataset is ~7.7k rows — small enough to fetch fully and match-filter in memory.

import os
from functools import lru_cache
from typing import Any, Dict, List, Tuple

import requests

from agent.schema import DBPRLicense, GoogleSeed
from utils.name_normalizer import normalize_name

# Nashville "Registered Professional Contractors and Licenses" Feature Service (layer 0).
TN_LICENSE_FEATURE_URL = os.getenv(
    "TN_LICENSE_FEATURE_URL",
    "https://services2.arcgis.com/HdTo6HJqh92wn4D8/arcgis/rest/services/"
    "Registered_Professional_Contractors_view_2/FeatureServer/0",
)
PAGE = 2000
TIMEOUT = 60

# Trade classifications relevant to our ICP (drywall contractors + general
# contractors). These are the exact Prof__Type values from the Nashville dataset
# that cover drywall-capable building work; everything else (plumbing, electrical,
# HVAC, roofing, septic, concrete, foundations, …) is filtered out at match time.
# The FL counterpart is scraper_dbpr.LICENSE_CATEGORIES — same idea, by-classification.
# Override the whole set without a code change via env TN_LICENSE_CLASSIFICATIONS
# (comma-separated). Matching is case/whitespace-insensitive.
DEFAULT_RELEVANT_CLASSIFICATIONS = (
    "General Contractor License",
    "State Building Contractor All",
    "State Commercial Building",
    "State Commercial Small Building",
    "State Residential Building",
    "State Residential Restricted To $125K",
    "State Home Improvement",
    "State Carpentry, Framming And Millwork",   # source spelling (sic)
    "State Painting, Interior Decorating",
    "State Masonry",
)


def _norm_class(s: str) -> str:
    return " ".join((s or "").lower().split())


@lru_cache(maxsize=1)
def _relevant_classifications() -> frozenset:
    env = os.getenv("TN_LICENSE_CLASSIFICATIONS")
    raw = env.split(",") if env else DEFAULT_RELEVANT_CLASSIFICATIONS
    return frozenset(_norm_class(c) for c in raw if c and c.strip())


def is_relevant_classification(prof_type: str) -> bool:
    """True if a Prof__Type classification is in-scope for our contractor ICP."""
    return _norm_class(prof_type) in _relevant_classifications()


_last_scanned = 0
_last_matched = 0
_last_filtered = 0


def _fetch_all_rows() -> List[Dict[str, Any]]:
    """Page through the ArcGIS Feature Service and return all attribute rows.

    The server caps each page at its own maxRecordCount (often < our requested
    PAGE), so we advance the offset by the rows ACTUALLY returned and stop only on
    an empty page (or when the server clears exceededTransferLimit)."""
    rows: List[Dict[str, Any]] = []
    offset = 0
    while True:
        resp = requests.get(
            TN_LICENSE_FEATURE_URL + "/query",
            params={
                "where": "1=1",
                "outFields": "Company_Name,Prof__Type,Address,City,ST,ZIP",
                "resultOffset": offset,
                "resultRecordCount": PAGE,
                "f": "json",
            },
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        feats = data.get("features", [])
        if not feats:
            break
        rows.extend(f.get("attributes", {}) for f in feats)
        offset += len(feats)
        if not data.get("exceededTransferLimit"):
            break
    return rows


@lru_cache(maxsize=1)
def _all_records() -> Tuple[Dict[str, Any], ...]:
    """All Nashville license rows, normalized for matching. Cached per process
    (fetched once, like dbpr's single stream)."""
    out: List[Dict[str, Any]] = []
    for a in _fetch_all_rows():
        # Some company names carry a leading '****' marker in the source — strip it.
        name = (a.get("Company_Name") or "").strip().lstrip("*").strip()
        if not name:
            continue
        out.append({
            "licensee_name": name,
            "normalized_name": normalize_name(name),
            "license_category": (a.get("Prof__Type") or "").strip(),   # classification
            "license_status": "registered",   # dataset lists current registrations
            "license_number": None,            # Nashville dataset exposes no license #
            "city": (a.get("City") or "").strip() or None,
            "state": (a.get("ST") or "").strip() or None,
            "zip_code": (a.get("ZIP") or "").strip() or None,
        })
    return tuple(out)


def query_by_normalized_names(normalized_names: List[str]) -> List[Dict[str, Any]]:
    """TN license records whose normalized company name matches any input AND whose
    trade classification is in scope for our contractor ICP (see
    RELEVANT_CLASSIFICATIONS — filter by classification, not the word 'drywall').
    Same contract as dbpr_loader.query_by_normalized_names. Returns [] on any
    failure — license is enrichment-only and must never block the pipeline."""
    global _last_scanned, _last_matched, _last_filtered
    targets = {n for n in normalized_names if n}
    if not targets:
        return []

    print(f"⬇️  [TN-license] fetching Nashville open data — matching {len(targets)} names")
    try:
        records = _all_records()
    except (requests.RequestException, ValueError) as e:
        print(f"⚠️  [TN-license] fetch failed ({e}) — skipping (enrichment only)")
        return []

    name_hits = [r for r in records if r["normalized_name"] in targets]
    # Keep only rows in an in-scope trade classification. A business that matches
    # by name but only on an unrelated trade (plumbing/electrical/…) yields no
    # license → it stays unvalidated, which is correct for a drywall/GC ICP.
    results = [r for r in name_hits if is_relevant_classification(r["license_category"])]
    _last_scanned, _last_matched, _last_filtered = len(records), len(results), len(name_hits) - len(results)
    print(f"✅ [TN-license] scanned {len(records)} rows, matched {len(results)} "
          f"by name+classification ({_last_filtered} name matches dropped "
          f"on off-scope classification; {len(targets)} names requested)")
    return results


def tn_license_count() -> int:
    """Rows scanned in the most recent load (0 before the first query)."""
    return _last_scanned


def _record_to_license(rec: Dict[str, Any]) -> DBPRLicense:
    """Adapt a Nashville record to the shared DBPRLicense shape so the existing
    name matcher (agent/matcher.py) works unchanged. Status is 'Current, Active'
    (the dataset lists current registrations); there is no license number, so the
    matcher keys on name + classification."""
    return DBPRLicense(
        license_number="",
        license_category=rec.get("license_category") or "",   # Prof__Type classification
        licensee_name=rec.get("licensee_name") or "",
        dba_name=None,
        status="Current, Active",
        city=rec.get("city"),
        zip_code=rec.get("zip_code"),
        phone=None,
        original_issue_date=None,
        raw=rec,
    )


def fetch_tn_licenses_for_seeds(seeds: List[GoogleSeed]) -> List[DBPRLicense]:
    """TN counterpart of scraper_dbpr.fetch_licenses_for_seeds: resolve Nashville
    open-data licenses for the discovered businesses (validation/enrichment only)."""
    names = sorted({s.business_name.strip() for s in seeds if getattr(s, "business_name", None)})
    if not names:
        return []
    recs = query_by_normalized_names([normalize_name(n) for n in names])
    return [_record_to_license(r) for r in recs]


if __name__ == "__main__":
    hits = query_by_normalized_names([normalize_name("OLD SOUTH CONSTRUCTION COMPANY")])
    print(f"Matched {len(hits)} record(s).")
    for h in hits[:3]:
        print(h)
