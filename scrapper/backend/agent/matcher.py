# matcher.py
# Fuzzy match Google seeds ↔ DBPR licenses — PDF Section 2.2 matching logic.
# Priority:
#   1. Exact match: normalized name + city
#   2. Exact match: normalized phone
#   3. Fuzzy: rapidfuzz token_set_ratio ≥ 88 within same ZIP

from typing import List, Optional, Dict
from rapidfuzz import fuzz

from agent.schema import GoogleSeed, DBPRLicense
from utils.phone_normalizer import normalize_phone
from utils.name_normalizer import normalize_name


FUZZY_THRESHOLD = 88


class LicenseMatch:
    def __init__(self, status: str, numbers: List[str], categories: List[str]):
        self.status = status
        self.numbers = numbers
        self.categories = categories


def _license_status_from_dbpr(dbpr_status: str) -> str:
    s = (dbpr_status or "").lower()
    if "current" in s or "active" in s:
        return "licensed_active"
    if "inactive" in s or "delinquent" in s or "null" in s or "void" in s:
        return "licensed_inactive"
    return "unknown"


def _aggregate(matches: List[DBPRLicense]) -> LicenseMatch:
    statuses = [_license_status_from_dbpr(m.status) for m in matches]
    best = "unknown"
    if "licensed_active" in statuses:
        best = "licensed_active"
    elif "licensed_inactive" in statuses:
        best = "licensed_inactive"
    return LicenseMatch(
        status=best,
        numbers=[m.license_number for m in matches],
        categories=list({m.license_category for m in matches}),
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


def match_license(seed: GoogleSeed, dbpr_index: List[DBPRLicense]) -> Optional[LicenseMatch]:
    """Find matching DBPR licenses for one Google seed. Returns aggregated match or None."""
    if not dbpr_index:
        return None

    seed_name = normalize_name(seed.business_name)
    seed_phone = normalize_phone(seed.phone) if seed.phone else None
    seed_zip = seed.zip_code

    matches: List[DBPRLicense] = []

    # 1. Exact name + city
    for lic in dbpr_index:
        if normalize_name(lic.licensee_name) == seed_name and (
            (lic.city or "").lower() == seed.city.lower()
        ):
            matches.append(lic)

    # 2. Exact phone
    if not matches and seed_phone:
        for lic in dbpr_index:
            lic_phone = normalize_phone(lic.phone) if lic.phone else None
            if lic_phone and lic_phone == seed_phone:
                matches.append(lic)

    # 3. Fuzzy name within same ZIP
    if not matches and seed_zip:
        for lic in dbpr_index:
            if lic.zip_code != seed_zip:
                continue
            score = fuzz.token_set_ratio(seed_name, normalize_name(lic.licensee_name))
            if score >= FUZZY_THRESHOLD:
                matches.append(lic)

    if not matches:
        return None

    # Aggregate: pick the "best" status (active > inactive > unknown)
    statuses = [_license_status_from_dbpr(m.status) for m in matches]
    best = "unknown"
    if "licensed_active" in statuses:
        best = "licensed_active"
    elif "licensed_inactive" in statuses:
        best = "licensed_inactive"

    return LicenseMatch(
        status=best,
        numbers=[m.license_number for m in matches],
        categories=list({m.license_category for m in matches}),
    )
