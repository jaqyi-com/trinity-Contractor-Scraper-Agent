# vendor.py
# Phase 4 — vendor-specific logic. Starts with alias resolution: map a discovered
# distributor's business name to its canonical NETWORK (GMS, L&W, FBM, …) so
# branches/brands roll up to one entity instead of being split or undercounted.

from typing import Dict, List, Optional

from agent.db import get_vendor_aliases
from utils.name_normalizer import normalize_name


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
