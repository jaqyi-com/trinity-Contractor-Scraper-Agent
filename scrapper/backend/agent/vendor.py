# vendor.py
# Phase 4 — vendor-specific logic: alias resolution (brand → canonical network) and
# distributor relevance (spec: "capture by drywall/gypsum CATEGORY, not a fixed
# name list"). The relevance check keeps actual material distributors/suppliers and
# drops contractors that the broad vendor search queries pull in.

import os
from typing import Dict, List, Optional

from agent.db import get_vendor_aliases
from utils.name_normalizer import normalize_name

# POSITIVE signals — drywall/gypsum/building-material DISTRIBUTOR (spec: "capture by
# drywall/gypsum category"). Deliberately NOT bare "supply" (plumbing/roofing/tool
# supply are not drywall distributors). Editable via env VENDOR_DISTRIBUTOR_SIGNALS.
_DEFAULT_DISTRIBUTOR_SIGNALS = (
    "drywall supply", "drywall distributor", "drywall and acoustical", "acoustical supply",
    "gypsum", "wallboard", "building material", "building materials", "building supply",
    "construction material", "construction supply", "material wholesaler", "materials supplier",
)
# NEGATIVE signals — a CONTRACTOR/installer (override: drop even if a minor supply
# category is present, e.g. a carpenter that also lists a "roofing supply store").
_CONTRACTOR_SIGNALS = (
    "contractor", "carpenter", "carpentry", "remodel", "installer", "installation",
    "framing", "plasterer",
)
_DISTRIBUTOR_SIGNALS = tuple(
    s.strip().lower() for s in os.getenv("VENDOR_DISTRIBUTOR_SIGNALS", "").split(",") if s.strip()
) or _DEFAULT_DISTRIBUTOR_SIGNALS


def is_distributor(business_name: str, categories: Optional[List[str]] = None) -> bool:
    """True if a business is a drywall/building-material DISTRIBUTOR (a sell-to
    target), not a contractor. Requires a building-material distributor signal AND
    no contractor signal — so a carpenter with a side 'roofing supply' category is
    NOT counted. Per the spec's 'capture by drywall/gypsum category' rule."""
    text = (str(business_name or "") + " " + " ".join(str(c) for c in (categories or []))).lower()
    if any(neg in text for neg in _CONTRACTOR_SIGNALS):
        return False
    return any(sig in text for sig in _DISTRIBUTOR_SIGNALS)


def _contains_phrase(name_norm: str, alias_norm: str) -> bool:
    """True if alias_norm appears in name_norm on word boundaries (so 'abc supply'
    matches 'abc supply interiors' but 'fbm' doesn't match inside another word)."""
    if not alias_norm:
        return False
    if name_norm == alias_norm:
        return True
    return f" {alias_norm} " in f" {name_norm} "


def resolve_vendor_network(business_name: str,
                           aliases: Optional[List[Dict[str, object]]] = None) -> Optional[Dict[str, object]]:
    """Resolve a vendor business name to its canonical network via the vendor_aliases
    map. Returns {canonical_network, entity, vendor_type, matched_alias} or None when
    no alias matches (caller then treats it as an independent, by category).
    The LONGEST matching alias wins (most specific brand)."""
    name_norm = normalize_name(business_name or "")
    if not name_norm:
        return None
    rows = aliases if aliases is not None else get_vendor_aliases()
    best = None
    best_len = -1
    for a in rows:
        alias_norm = normalize_name(str(a.get("alias") or ""))
        if _contains_phrase(name_norm, alias_norm) and len(alias_norm) > best_len:
            best, best_len = a, len(alias_norm)
    if not best:
        return None
    return {
        "canonical_network": best.get("canonical_network"),
        "entity": best.get("entity"),
        "vendor_type": best.get("vendor_type") or "specialty_distributor",
        "matched_alias": best.get("alias"),
    }
