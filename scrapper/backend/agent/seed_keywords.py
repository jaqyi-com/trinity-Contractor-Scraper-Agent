# seed_keywords.py
# One-time seed: insert PDF Section 1.2 + 3.3 keywords into `keywords` table.
# Run with: python -m agent.seed_keywords

from agent.db import _get_conn, init_schema


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
    """Insert seed keywords if `keywords` table is empty."""
    init_schema()
    conn = _get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM keywords")
            count = cur.fetchone()[0]
            if count > 0:
                print(f"⏩ Keywords table already has {count} rows — skipping seed")
                return

            inserted = 0
            for tier, words in SEED.items():
                for kw in words:
                    cur.execute(
                        """
                        INSERT INTO keywords (tier, keyword, created_by)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (tier, keyword) DO NOTHING
                        """,
                        (tier, kw.lower(), "system"),
                    )
                    inserted += 1
            print(f"✅ Seeded {inserted} keywords from PDF defaults")
    finally:
        conn.close()


if __name__ == "__main__":
    seed_keywords()
