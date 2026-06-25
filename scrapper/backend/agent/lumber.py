# lumber.py
# Phase 5 — Lumber exclusion (Workstream D). A robust 3-layer filter, because a
# single "exclude the word lumber" rule has already proven insufficient.
#
#   Layer 1 (category)     — source category (Google/BBB) signals lumber/sawmill
#   Layer 2 (keyword)      — editable negative-keyword list on name + description
#   Layer 3 (name_pattern) — regex catches a lumber-signaling name with a clean category
#
# Applied to BOTH the contractor and vendor pipelines. Matches FLAG the record
# (excluded_reason) — they are never hard-deleted, so the "wide net" is preserved
# and every exclusion stays auditable; the deliverable view filters flagged rows.

import re
from typing import Any, Dict, List, Optional

from agent.db import get_negative_keywords


def _normalize(text: str) -> str:
    """Lowercase + turn any non-alphanumeric (incl. underscores in category codes
    like 'lumber_store') into spaces, so word-boundary matching works uniformly."""
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _word_match(text: str, term: str) -> bool:
    """Word-boundary match on normalized text (so 'lumber' matches 'lumber store'
    and 'lumber_store' but NOT 'plumber')."""
    if not term:
        return False
    return f" {_normalize(term)} " in f" {_normalize(text)} "


def check_lumber(record: Dict[str, Any], terms: Optional[List[Dict[str, Any]]] = None) -> Optional[str]:
    """Return an excluded_reason string (e.g. 'lumber:category:lumberyard') if the
    record trips any lumber-exclusion layer, else None. `record` may expose
    business_name, description, google_categories (list)."""
    rows = terms if terms is not None else get_negative_keywords()
    name = (record.get("business_name") or "").lower()
    desc = (record.get("description") or "").lower()
    cats = [str(c).lower() for c in (record.get("google_categories") or [])]
    name_desc = f"{name} {desc}".strip()

    for t in rows:
        term = str(t.get("term") or "")
        layer = (t.get("layer") or "keyword").lower()
        if not term:
            continue
        low = term.lower()
        if layer == "category":
            if any(_word_match(c, low) for c in cats):
                return f"lumber:category:{term}"
        elif layer == "keyword":
            if _word_match(name_desc, low):
                return f"lumber:keyword:{term}"
        elif layer == "name_pattern":
            try:
                if re.search(term, name, flags=re.IGNORECASE):
                    return f"lumber:name_pattern:{term}"
            except re.error:
                continue
    return None


def apply_lumber_flag(record: Dict[str, Any], terms: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Set record['excluded_reason'] if the record is lumber (flag, don't delete).
    Won't overwrite an existing exclusion reason. Returns the same record."""
    if record.get("excluded_reason"):
        return record
    reason = check_lumber(record, terms)
    if reason:
        record["excluded_reason"] = reason
    return record
