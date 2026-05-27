# dedupe.py
# Dedup rules — PDF Section 3.4 priority order:
#   1. Exact normalized phone
#   2. Exact normalized website domain
#   3. Fuzzy name (rapidfuzz ≥ 90) + same ZIP
#   4. Exact normalized address

from typing import List, Dict
from rapidfuzz import fuzz

from agent.schema import ContractorRow
from utils.phone_normalizer import normalize_phone
from utils.url_normalizer import extract_domain
from utils.name_normalizer import normalize_name
from utils.address_normalizer import normalize_address


FUZZY_NAME_THRESHOLD = 90


def _merge(a: ContractorRow, b: ContractorRow) -> ContractorRow:
    """Keep the most complete record. Merge place_ids + sources + license_numbers."""
    merged = a.model_copy(deep=True)
    for field in a.model_fields:
        a_val = getattr(a, field)
        b_val = getattr(b, field)
        if not a_val and b_val:
            setattr(merged, field, b_val)
    merged.place_ids = list({*a.place_ids, *b.place_ids})
    merged.sources = list({*a.sources, *b.sources})
    merged.license_numbers = list({*a.license_numbers, *b.license_numbers})
    return merged


def dedupe(rows: List[ContractorRow]) -> List[ContractorRow]:
    """Apply PDF 3.4 dedup priority. Returns deduplicated list."""
    by_phone: Dict[str, ContractorRow] = {}
    by_domain: Dict[str, ContractorRow] = {}
    by_address: Dict[str, ContractorRow] = {}
    remaining: List[ContractorRow] = []

    # Step 1: phone
    for row in rows:
        phone = normalize_phone(row.phone) if row.phone else None
        if phone:
            if phone in by_phone:
                by_phone[phone] = _merge(by_phone[phone], row)
            else:
                by_phone[phone] = row
        else:
            remaining.append(row)

    # Step 2: domain (within remaining)
    phase2: List[ContractorRow] = list(by_phone.values()) + remaining
    deduped_phase2: List[ContractorRow] = []
    for row in phase2:
        domain = extract_domain(row.website) if row.website else None
        if domain:
            if domain in by_domain:
                by_domain[domain] = _merge(by_domain[domain], row)
            else:
                by_domain[domain] = row
        else:
            deduped_phase2.append(row)
    deduped_phase2.extend(by_domain.values())

    # Step 3: fuzzy name + ZIP
    final: List[ContractorRow] = []
    for row in deduped_phase2:
        matched_idx = -1
        rname = normalize_name(row.business_name)
        for i, kept in enumerate(final):
            if kept.zip_code != row.zip_code:
                continue
            if fuzz.token_set_ratio(rname, normalize_name(kept.business_name)) >= FUZZY_NAME_THRESHOLD:
                matched_idx = i
                break
        if matched_idx >= 0:
            final[matched_idx] = _merge(final[matched_idx], row)
        else:
            final.append(row)

    # Step 4: exact address
    by_address.clear()
    final2: List[ContractorRow] = []
    for row in final:
        addr = normalize_address(row.address) if row.address else None
        if addr:
            if addr in by_address:
                by_address[addr] = _merge(by_address[addr], row)
            else:
                by_address[addr] = row
        else:
            final2.append(row)
    final2.extend(by_address.values())

    return final2


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
