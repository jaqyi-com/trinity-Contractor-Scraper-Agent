# matcher.py
# Match Google seeds ↔ DBPR licenses by business name (PDF Section 2.2).
# Because the DBPR index is pulled BY business name (bulk table / Apify orgName
# search), matching is name-based — a company's licensed address often differs
# from its Google listing, so ZIP/city can't be used.

from typing import List, Optional
from rapidfuzz import fuzz

from agent.schema import GoogleSeed, DBPRLicense
from utils.name_normalizer import normalize_name


class LicenseMatch:
    def __init__(self, status: str, numbers: List[str], categories: List[str]):
        self.status = status
        self.numbers = numbers
        self.categories = categories


def _license_status_from_dbpr(dbpr_status: str) -> str:
    s = (dbpr_status or "").lower()
    # Check inactive FIRST — "inactive" contains the substring "active",
    # and "Current, Inactive" contains "current", so order matters.
    if "inactive" in s or "delinquent" in s or "null" in s or "void" in s or "suspend" in s:
        return "licensed_inactive"
    if "current" in s or "active" in s:
        return "licensed_active"
    return "unknown"


def _aggregate(matches: List[DBPRLicense]) -> LicenseMatch:
    statuses = [_license_status_from_dbpr(m.status) for m in matches]
    numbers = sorted({m.license_number for m in matches if m.license_number})
    best = "unknown"
    if "licensed_active" in statuses:
        best = "licensed_active"
    elif "licensed_inactive" in statuses:
        best = "licensed_inactive"
    elif numbers:
        # A real license number was matched but the status string was unclear —
        # the business IS licensed, so don't mislabel it "unknown".
        best = "licensed_active"
    return LicenseMatch(
        status=best,
        numbers=numbers,
        categories=sorted({m.license_category for m in matches if m.license_category}),
    )


def match_license_by_name(seed: GoogleSeed, dbpr_index: List[DBPRLicense]) -> Optional[LicenseMatch]:
    """
    Name-only match — used when the DBPR index was pulled BY business name
    (Apify orgName search). Address/ZIP can't be used because a company's
    licensed address often differs from its Google listing location.

    Exact normalized-name match first; fall back to fuzzy ≥ 92 to stay clear
    of unrelated same-surname records (e.g. a person who shares one token).
    """
    if not dbpr_index:
        return None

    seed_name = normalize_name(seed.business_name)
    if not seed_name:
        return None

    exact = [lic for lic in dbpr_index if normalize_name(lic.licensee_name) == seed_name
             or (lic.dba_name and normalize_name(lic.dba_name) == seed_name)]
    if exact:
        return _aggregate(exact)

    fuzzy = [lic for lic in dbpr_index
             if fuzz.token_set_ratio(seed_name, normalize_name(lic.licensee_name)) >= 92]
    if fuzzy:
        return _aggregate(fuzzy)

    return None
