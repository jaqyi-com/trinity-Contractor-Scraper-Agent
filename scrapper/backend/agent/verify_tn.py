# verify_tn.py
# OPTIONAL statewide Tennessee contractor-license verification — the "verify-a-name"
# path from the spec (verify.tn.gov / search.cloud.commerce.tn.gov).
#
# WHY THIS IS SPECIAL (read before enabling):
#   Tennessee publishes NO Florida-style bulk download and NO documented public
#   API for its statewide licensee roster. The state portal returns ONE record per
#   name you look up. So this can only be a per-NAME enrichment: one HTTP round-trip
#   per business. On a large TN run that means it can add MINUTES (it is gated by a
#   per-run cap, TN_VERIFY_MAX_LOOKUPS, to keep it bounded).
#
#   It is therefore OFF by default (Settings → "Statewide TN license verify"). It is
#   ENRICHMENT only — it never drives discovery (discovery stays Google + BBB +
#   keywords) and it NEVER blocks the pipeline: every failure degrades to [].
#
#   Because the state exposes no stable public endpoint, the lookup URL is
#   env-configurable (TN_VERIFY_SEARCH_URL). When it is unset or unreachable we log
#   once and skip — the run continues exactly as if the toggle were off. Whoever
#   wires the real endpoint only edits the env var + (if needed) _parse_hit().
#
# Results are filtered by trade CLASSIFICATION (same rule as the Nashville path) —
# we validate by classification, not the word "drywall".

import os
from typing import Any, Dict, List, Optional

import requests

from agent.schema import DBPRLicense, GoogleSeed
from agent.scraper_tn_license import is_relevant_classification
from utils.name_normalizer import normalize_name

# The state portal has no documented public API, so the endpoint is configurable.
# Expected to accept a business-name query param and return JSON. Leave unset to
# keep the feature inert even when the toggle is on (we log + skip).
TN_VERIFY_SEARCH_URL = os.getenv("TN_VERIFY_SEARCH_URL")          # e.g. a JSON search endpoint
TN_VERIFY_NAME_PARAM = os.getenv("TN_VERIFY_NAME_PARAM", "name")  # query-param key for the name
# Bound the per-run cost: at most this many name lookups per run (the rest skipped,
# logged). One lookup ≈ one HTTP round-trip, so 200 × ~1s ≈ a few minutes worst case.
TN_VERIFY_MAX_LOOKUPS = int(os.getenv("TN_VERIFY_MAX_LOOKUPS", "200"))
TIMEOUT = 30

_warned = False


def _parse_hit(name: str, data: Any) -> Optional[Dict[str, Any]]:
    """Pull a license record out of the portal's response, tolerating shape
    variations. Returns a normalized dict or None. Adjust here if the configured
    endpoint returns a different schema."""
    # Accept either a bare object or {results:[...]} / a list — take the first hit.
    rec = data
    if isinstance(data, dict):
        for key in ("results", "data", "items", "records"):
            if isinstance(data.get(key), list) and data[key]:
                rec = data[key][0]
                break
    if isinstance(rec, list):
        rec = rec[0] if rec else None
    if not isinstance(rec, dict):
        return None

    def pick(*keys):
        for k in keys:
            v = rec.get(k)
            if v not in (None, ""):
                return v
        return None

    return {
        "licensee_name": pick("company_name", "name", "licensee_name", "business_name") or name,
        "license_category": (pick("classification", "license_type", "prof_type", "type") or "").strip(),
        "license_number": pick("license_number", "number", "license_no"),
        "status": (pick("status", "license_status") or "Active"),
        "city": pick("city"),
        "zip_code": pick("zip", "zip_code", "postal_code"),
    }


def _lookup_one(name: str) -> Optional[DBPRLicense]:
    """One verify-a-name round-trip. Returns a DBPRLicense (same shape the matcher
    consumes) or None. Never raises."""
    global _warned
    if not TN_VERIFY_SEARCH_URL:
        if not _warned:
            print("⚠️  [TN-verify] enabled but TN_VERIFY_SEARCH_URL is unset — skipping (set the env var to use it)")
            _warned = True
        return None
    try:
        resp = requests.get(TN_VERIFY_SEARCH_URL, params={TN_VERIFY_NAME_PARAM: name}, timeout=TIMEOUT)
        resp.raise_for_status()
        rec = _parse_hit(name, resp.json())
    except (requests.RequestException, ValueError) as e:
        if not _warned:
            print(f"⚠️  [TN-verify] lookup failed ({e}) — skipping remaining (enrichment only)")
            _warned = True
        return None
    if not rec:
        return None
    # Filter by classification (not the word "drywall") — same rule as Nashville.
    if rec["license_category"] and not is_relevant_classification(rec["license_category"]):
        return None
    return DBPRLicense(
        license_number=rec.get("license_number") or "",
        license_category=rec.get("license_category") or "",
        licensee_name=rec.get("licensee_name") or "",
        dba_name=None,
        status=rec.get("status") or "Active",
        city=rec.get("city"),
        zip_code=rec.get("zip_code"),
        phone=None,
        original_issue_date=None,
        raw=rec,
    )


def verify_tn_for_seeds(seeds: List[GoogleSeed],
                        already: Optional[List[DBPRLicense]] = None) -> List[DBPRLicense]:
    """Statewide per-name verify for TN businesses NOT already matched by Nashville
    open data. Bounded by TN_VERIFY_MAX_LOOKUPS. Enrichment-only, never raises."""
    matched = {normalize_name(l.licensee_name) for l in (already or []) if l.licensee_name}
    names = sorted({s.business_name.strip() for s in seeds
                    if getattr(s, "business_name", None) and normalize_name(s.business_name) not in matched})
    if not names:
        return []

    todo, skipped = names[:TN_VERIFY_MAX_LOOKUPS], max(0, len(names) - TN_VERIFY_MAX_LOOKUPS)
    print(f"🔎 [TN-verify] statewide verify-a-name for {len(todo)} business(es)"
          + (f" (capped — {skipped} skipped this run; raise TN_VERIFY_MAX_LOOKUPS)" if skipped else ""))
    out: List[DBPRLicense] = []
    for n in todo:
        lic = _lookup_one(n)
        if lic is None and _warned:   # endpoint unset/broken — stop hammering it
            break
        if lic:
            out.append(lic)
    print(f"✅ [TN-verify] matched {len(out)} record(s) by name+classification")
    return out
