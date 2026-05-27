# classifier.py
# Tier classifier — PDF Section 3.3 pseudocode.
# Loads keywords from DB, classifies each row, returns ClassificationDecision.

from typing import List, Dict, Any
from agent.schema import GoogleSeed, ClassificationDecision, MatchedKeyword


def _build_classifier_text(seed: GoogleSeed) -> str:
    """Combine all signal fields into a single lowercase blob for keyword scanning."""
    parts = [
        seed.business_name or "",
        " ".join(seed.google_categories or []),
        " ".join(seed.services_listed or []),
        seed.description or "",
    ]
    return " ".join(parts).lower()


def _bucket(keywords: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Group keywords by tier."""
    out: Dict[str, List[str]] = {}
    for kw in keywords:
        out.setdefault(kw["tier"], []).append(kw["keyword"].lower())
    return out


def classify(
    seed: GoogleSeed,
    keywords: List[Dict[str, Any]],
) -> ClassificationDecision:
    """
    Apply PDF Section 3.3 pseudocode:
      1. EXCLUDE_HARD (and no in-scope) → EXCLUDED
      2. EXCLUDE_SOLO (and no in-scope) → EXCLUDED
      3. TIER_1_DRYWALL → INCLUDED
      4. TIER_1_GC (with drywall in scope) → INCLUDED as TIER_1_GC_WITH_SCOPE
      5. TIER_1_GC alone → INCLUDED as TIER_2_GC_GENERIC
      6. TIER_2_PAINTER → INCLUDED
      7. TIER_2_REMODELER → INCLUDED
      8. TIER_3_HANDYMAN → INCLUDED
      9. else → EXCLUDED
    """
    text = _build_classifier_text(seed)
    buckets = _bucket(keywords)

    def hits(tier: str) -> List[str]:
        return [k for k in buckets.get(tier, []) if k in text]

    drywall_hits = hits("TIER_1_DRYWALL")
    gc_hits = hits("TIER_1_GC")
    paint_hits = hits("TIER_2_PAINTER")
    remodel_hits = hits("TIER_2_REMODELER")
    handyman_hits = hits("TIER_3_HANDYMAN")
    hard_excl = hits("EXCLUDE_HARD")
    solo_excl = hits("EXCLUDE_SOLO")

    has_target = bool(drywall_hits or gc_hits or paint_hits or remodel_hits or handyman_hits)

    # Build matched + exclusion lists for audit
    matched: List[MatchedKeyword] = []
    for tier_name, hit_list in [
        ("TIER_1_DRYWALL", drywall_hits),
        ("TIER_1_GC", gc_hits),
        ("TIER_2_PAINTER", paint_hits),
        ("TIER_2_REMODELER", remodel_hits),
        ("TIER_3_HANDYMAN", handyman_hits),
    ]:
        for k in hit_list:
            matched.append(MatchedKeyword(tier=tier_name, keyword=k))

    exclusion: List[MatchedKeyword] = []
    for tier_name, hit_list in [("EXCLUDE_HARD", hard_excl), ("EXCLUDE_SOLO", solo_excl)]:
        for k in hit_list:
            exclusion.append(MatchedKeyword(tier=tier_name, keyword=k))

    # Rule: hard exclude AND no in-scope → EXCLUDED
    if hard_excl and not has_target:
        return ClassificationDecision(
            decision="EXCLUDED",
            assigned_tier="EXCLUDE",
            matched_keywords=matched,
            exclusion_keywords=exclusion,
            classifier_text=text[:500],
            reason=f"Matched hard exclusion: {', '.join(hard_excl)} (no in-scope keywords present)",
        )

    # Rule: solo exclude AND no in-scope → EXCLUDED
    if solo_excl and not has_target:
        return ClassificationDecision(
            decision="EXCLUDED",
            assigned_tier="EXCLUDE",
            matched_keywords=matched,
            exclusion_keywords=exclusion,
            classifier_text=text[:500],
            reason=f"Matched solo-trade exclusion: {', '.join(solo_excl)} (no in-scope keywords present)",
        )

    # Tier assignment — most specific first
    if drywall_hits:
        return ClassificationDecision(
            decision="INCLUDED",
            assigned_tier="TIER_1_DRYWALL",
            matched_keywords=matched,
            exclusion_keywords=exclusion,
            classifier_text=text[:500],
            reason=f"Matched TIER_1_DRYWALL: {', '.join(drywall_hits)}",
        )

    if gc_hits and (drywall_hits or paint_hits or remodel_hits):
        return ClassificationDecision(
            decision="INCLUDED",
            assigned_tier="TIER_1_GC_WITH_SCOPE",
            matched_keywords=matched,
            exclusion_keywords=exclusion,
            classifier_text=text[:500],
            reason=f"GC with in-scope work: {', '.join(gc_hits)}",
        )

    if gc_hits:
        return ClassificationDecision(
            decision="INCLUDED",
            assigned_tier="TIER_2_GC_GENERIC",
            matched_keywords=matched,
            exclusion_keywords=exclusion,
            classifier_text=text[:500],
            reason=f"Generic GC: {', '.join(gc_hits)}",
        )

    if paint_hits:
        return ClassificationDecision(
            decision="INCLUDED",
            assigned_tier="TIER_2_PAINTER",
            matched_keywords=matched,
            exclusion_keywords=exclusion,
            classifier_text=text[:500],
            reason=f"Painter: {', '.join(paint_hits)}",
        )

    if remodel_hits:
        return ClassificationDecision(
            decision="INCLUDED",
            assigned_tier="TIER_2_REMODELER",
            matched_keywords=matched,
            exclusion_keywords=exclusion,
            classifier_text=text[:500],
            reason=f"Remodeler: {', '.join(remodel_hits)}",
        )

    if handyman_hits:
        return ClassificationDecision(
            decision="INCLUDED",
            assigned_tier="TIER_3_HANDYMAN",
            matched_keywords=matched,
            exclusion_keywords=exclusion,
            classifier_text=text[:500],
            reason=f"Handyman: {', '.join(handyman_hits)}",
        )

    return ClassificationDecision(
        decision="EXCLUDED",
        assigned_tier="EXCLUDE",
        matched_keywords=matched,
        exclusion_keywords=exclusion,
        classifier_text=text[:500],
        reason="No tier keywords matched",
    )
