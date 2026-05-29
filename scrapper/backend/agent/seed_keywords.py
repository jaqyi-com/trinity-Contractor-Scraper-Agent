# seed_keywords.py
# One-time seed: insert PDF Section 1.2 + 3.3 keywords into the keywords tab.
# Run with: python -m agent.seed_keywords

from agent import db


SEED = {
    # PDF Section 3.3 — DRYWALL_KW
    "TIER_1_DRYWALL": [
        "drywall", "sheetrock", "gypsum", "plaster", "taping",
        "mudding", "popcorn ceiling", "knockdown", "orange peel",
        "skim coat", "drywall texturing", "drywall repair", "level 5",
        "drywall finishing", "plasterer",
    ],

    # PDF Section 3.3 — GC_KW
    "TIER_1_GC": [
        "general contractor", "general contracting", "construction services",
    ],

    # PDF Section 3.3 — PAINT_KW
    "TIER_2_PAINTER": [
        "painter", "painting", "painting contractor", "residential painter",
        "interior painter", "drywall and paint", "paint and patch",
    ],

    # PDF Section 3.3 — REMODEL_KW
    "TIER_2_REMODELER": [
        "remodel", "renovation", "home improvement", "home renovation",
        "interior remodel", "residential renovation",
    ],

    # PDF Section 3.3 — HANDYMAN_KW
    "TIER_3_HANDYMAN": [
        "handyman", "handyperson", "home repair",
        "property maintenance", "small repairs",
    ],

    # PDF Section 3.3 — EXCLUDE_KW (hard exclusions)
    "EXCLUDE_HARD": [
        "hvac", "air conditioning", "ac repair", "heating",
        "asphalt", "paving", "concrete pouring", "concrete contractor",
        "landscap", "lawn care", "tree service",
        "pool", "pest control",
        "septic", "well drilling", "locksmith",
        "garage door", "junk removal", "cleaning service",
    ],

    # PDF Section 3.3 — SOLO_EXCLUDE (only if nothing in-scope is also present)
    "EXCLUDE_SOLO": [
        "roofing", "plumbing", "electrical", "flooring",
        "tile", "window", "fence",
    ],
}


def seed_keywords():
    """Insert seed keywords if the keywords tab is empty."""
    db.init_schema()
    existing = db.list_keywords()
    if existing:
        print(f"⏩ Keywords already has {len(existing)} rows — skipping seed")
        return

    inserted = 0
    for tier, words in SEED.items():
        for kw in words:
            row = db.insert_keyword_raw(tier, kw.lower(), notes=None, created_by="system")
            if row:
                inserted += 1
    print(f"✅ Seeded {inserted} keywords from PDF defaults")


if __name__ == "__main__":
    seed_keywords()
