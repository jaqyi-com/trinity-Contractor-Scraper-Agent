# dedupe.py
# Two dedupe layers, both PDF Section 3.4 (phone → domain → name+loc):
#
#   dedupe_seeds()        — runs RIGHT AFTER Google discovery, BEFORE any paid
#                           enrichment (BBB/Apollo). Collapsing duplicate seeds
#                           here means we never spend enrichment credits twice on
#                           the same business (e.g. a contractor listed in two
#                           metros, or returned under several search queries).
#   dedupe_all_for_job()  — post-insert belt-and-suspenders sweep over the DB.
#
# Insert-time UPSERT (db.insert_contractor, keyed on dedupe_key) is the third net.

from typing import Dict, List

from agent.schema import GoogleSeed
from utils.phone_normalizer import normalize_phone
from utils.url_normalizer import extract_domain
from utils.name_normalizer import normalize_name


def _seed_dedupe_key(seed: GoogleSeed) -> str:
    """Canonical key for a raw seed — mirrors db.compute_dedupe_key's priority
    (normalized phone → website domain → normalized name + zip/city)."""
    phone = normalize_phone(seed.phone) if seed.phone else None
    if phone:
        return f"phone:{phone}"
    domain = extract_domain(seed.website) if seed.website else None
    if domain:
        return f"domain:{domain}"
    name = normalize_name(seed.business_name or "")
    loc = (seed.zip_code or seed.city or "").strip()
    return f"name:{name}|{loc}"


def dedupe_seeds(seeds: List[GoogleSeed]) -> List[GoogleSeed]:
    """
    Collapse duplicate discovery seeds before enrichment (the expensive stage).

    Keeps the first seed seen per canonical key, backfills its missing contact
    fields + social profiles from the dropped twins, and accumulates the twins'
    place_ids into `merged_place_ids` so no provenance is lost. Order is
    preserved (stable) for predictable downstream behaviour.
    """
    survivors: Dict[str, GoogleSeed] = {}
    order: List[str] = []

    for s in seeds:
        key = _seed_dedupe_key(s)
        keep = survivors.get(key)
        if keep is None:
            survivors[key] = s
            order.append(key)
            s.merged_place_ids = [s.place_id] if s.place_id else []
            continue

        # Merge the duplicate into the survivor (no new enrichment cost).
        if s.place_id and s.place_id not in keep.merged_place_ids:
            keep.merged_place_ids.append(s.place_id)
        keep.email = keep.email or s.email
        keep.phone = keep.phone or s.phone
        keep.website = keep.website or s.website
        keep.description = keep.description or s.description
        if keep.google_rating is None:
            keep.google_rating = s.google_rating
            keep.google_review_count = s.google_review_count
        for k, v in (s.social_profiles or {}).items():
            keep.social_profiles.setdefault(k, v)

    result = [survivors[k] for k in order]
    print(f"🧹 [Dedupe seeds] {len(seeds)} raw → {len(result)} unique "
          f"({len(seeds) - len(result)} duplicates removed before enrichment)")
    return result


def dedupe_all_for_job(job_id: str) -> dict:
    """
    DB-level dedupe for one job, PDF 3.4 keys 1–2 (exact phone, exact domain).
    Keeps the lowest-id row in each duplicate group, merges place_ids + sources
    into it, and deletes the extras. Returns a small summary.
    """
    from psycopg2.extras import RealDictCursor
    from agent.db import _get_conn
    import json

    print(f"🔁 [Dedupe] job_id={job_id}")
    conn = _get_conn()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """SELECT id, phone, website, place_ids, sources
                   FROM contractors WHERE job_id = %s ORDER BY id""",
                (job_id,),
            )
            rows = cur.fetchall()

            survivor_by_key: Dict[str, int] = {}   # "phone:..."/"domain:..." -> survivor id
            merge_into: Dict[int, int] = {}         # dup id -> survivor id

            for r in rows:
                keys = []
                if r["phone"]:
                    p = normalize_phone(r["phone"])
                    if p:
                        keys.append(f"phone:{p}")
                if r["website"]:
                    d = extract_domain(r["website"])
                    if d:
                        keys.append(f"domain:{d}")

                survivor = next((survivor_by_key[k] for k in keys if k in survivor_by_key), None)
                if survivor is None:
                    for k in keys:
                        survivor_by_key[k] = r["id"]
                else:
                    merge_into[r["id"]] = survivor
                    for k in keys:
                        survivor_by_key.setdefault(k, survivor)

            # Merge dup place_ids/sources into survivors, then delete dups.
            row_by_id = {r["id"]: r for r in rows}
            survivor_updates: Dict[int, dict] = {}
            for dup_id, surv_id in merge_into.items():
                dup, surv = row_by_id[dup_id], row_by_id[surv_id]
                acc = survivor_updates.setdefault(surv_id, {
                    "place_ids": set(surv["place_ids"] or []),
                    "sources": set(surv["sources"] or []),
                })
                acc["place_ids"].update(dup["place_ids"] or [])
                acc["sources"].update(dup["sources"] or [])

            for surv_id, acc in survivor_updates.items():
                cur.execute(
                    "UPDATE contractors SET place_ids = %s, sources = %s WHERE id = %s",
                    (json.dumps(sorted(acc["place_ids"])), json.dumps(sorted(acc["sources"])), surv_id),
                )

            dup_ids = list(merge_into.keys())
            if dup_ids:
                cur.execute("DELETE FROM contractors WHERE id = ANY(%s)", (dup_ids,))

        summary = {"total": len(rows), "duplicates_removed": len(merge_into), "kept": len(rows) - len(merge_into)}
        print(f"🔁 [Dedupe] {summary}")
        return summary
    finally:
        conn.close()
