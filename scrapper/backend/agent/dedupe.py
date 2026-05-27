# dedupe.py
# Cross-metro dedupe for one job — PDF Section 3.4 keys 1–2 (exact phone, exact
# domain). Insert-time UPSERT (db.insert_contractor, keyed on dedupe_key) already
# prevents most duplicates; this is the belt-and-suspenders sweep per job.

from typing import Dict

from utils.phone_normalizer import normalize_phone
from utils.url_normalizer import extract_domain


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
