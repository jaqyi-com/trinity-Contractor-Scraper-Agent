# db.py
# Storage layer — Google Sheets (replaces psycopg2/Postgres).
#
# The public surface mirrors the old Postgres helpers byte-for-byte so callers
# (pipeline, processor, api/routes/*) don't change: same function names, same
# arguments, same return shapes. The bodies route through agent.sheets_client,
# which holds an in-memory mirror + batched write buffer + background flusher.
#
# DBPR licenses are NOT stored here anymore — they live in a per-process pandas
# DataFrame loaded from the official Florida CSV on demand (see dbpr_loader.py).

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from agent.sheets_client import get_db
from utils.phone_normalizer import normalize_phone
from utils.url_normalizer import extract_domain
from utils.name_normalizer import normalize_name

load_dotenv()


# ──────────────────────────────────────────────────────────────
# Schema bootstrap — equivalent of old init_schema() but for Sheets.
# Connects, creates missing tabs + header rows, loads mirror into RAM.
# Idempotent: safe to call from FastAPI lifespan, CLI scripts, tests.
# ──────────────────────────────────────────────────────────────
def init_schema() -> None:
    db = get_db()
    # bootstrap() is itself idempotent (no-op after first call).
    db.bootstrap()
    # Seed defaults (also idempotent: each checks for existing rows first).
    _seed_test_user_if_missing()
    _seed_cities_from_yaml_if_empty()


# Back-compat shim — a few callers still import `_get_conn`. After the rewrite
# nothing should actually call it; raising loudly makes any stragglers obvious.
def _get_conn():  # noqa: D401
    raise RuntimeError(
        "_get_conn() removed: storage moved from Postgres to Google Sheets. "
        "Use the typed helpers in agent/db.py (e.g. list_keywords, list_classification_log)."
    )


# ──────────────────────────────────────────────────────────────
# Dedupe key — same rule the old Postgres UPSERT used (phone → domain → name+loc).
# ──────────────────────────────────────────────────────────────
def compute_dedupe_key(record: Dict[str, Any]) -> str:
    phone = normalize_phone(record.get("phone")) if record.get("phone") else None
    if phone:
        return f"phone:{phone}"
    domain = extract_domain(record.get("website")) if record.get("website") else None
    if domain:
        return f"domain:{domain}"
    name = normalize_name(record.get("business_name") or "")
    loc = (record.get("zip_code") or record.get("city") or "").strip()
    return f"name:{name}|{loc}"


# ──────────────────────────────────────────────────────────────
# Seed defaults — called from init_schema; safe to re-run.
# ──────────────────────────────────────────────────────────────
def _seed_test_user_if_missing() -> None:
    """Ensure a test user exists. Email 'test@example.com', password '123456'."""
    db = get_db()
    if db.find_one("users", lambda r: r.get("email") == "test@example.com"):
        return
    from api.auth import hash_password
    now = datetime.utcnow()
    db.insert("users", {
        "email": "test@example.com",
        "name": "Test User",
        "password_hash": hash_password("123456"),
        "created_at": now,
    })
    print("✅ Seeded test user: test@example.com / 123456")


def _seed_cities_from_yaml_if_empty() -> None:
    """Load config/cities.yaml into cities + city_zips tabs on first boot."""
    import yaml
    from pathlib import Path

    db = get_db()
    if db.count("cities") > 0:
        return

    yaml_path = Path(__file__).resolve().parent.parent / "config" / "cities.yaml"
    if not yaml_path.exists():
        print(f"⏩ No cities.yaml at {yaml_path} — skipping city seed")
        return

    data = yaml.safe_load(yaml_path.read_text())
    cities = data.get("cities", []) if isinstance(data, dict) else []
    total_zips = 0
    now = datetime.utcnow()
    for c in cities:
        city = db.insert("cities", {
            "name": c.get("name"),
            "state": c.get("state", "FL"),
            "created_at": now,
            "updated_at": now,
        })
        for z in c.get("zips", []) or []:
            db.insert("city_zips", {
                "city_id": city["id"],
                "zip_code": str(z),
                "created_at": now,
            })
            total_zips += 1
    print(f"✅ Seeded {len(cities)} cities + {total_zips} ZIPs from cities.yaml")


# ──────────────────────────────────────────────────────────────
# Jobs
# ──────────────────────────────────────────────────────────────
def create_job() -> str:
    job_id = str(uuid.uuid4())
    db = get_db()
    db.insert("jobs", {
        "job_id": job_id,
        "status": "pending",
        "started_at": datetime.utcnow(),
    })
    return job_id


def update_job(job_id: str, **fields) -> None:
    if not fields:
        return
    db = get_db()
    # Old Postgres code JSON-encoded these before passing through; now the sheets
    # encoder handles JSON serialisation, so we just hand the native dict in.
    db.update("jobs", job_id, fields)


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    return get_db().get_by_id("jobs", job_id)


def list_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    rows = get_db().all_rows("jobs")
    rows.sort(key=lambda r: _dt_key(r.get("started_at")), reverse=True)
    return rows[:limit]


def get_running_job() -> Optional[Dict[str, Any]]:
    rows = get_db().find("jobs", lambda r: r.get("status") in ("pending", "running"))
    if not rows:
        return None
    rows.sort(key=lambda r: _dt_key(r.get("started_at")), reverse=True)
    return rows[0]


# ──────────────────────────────────────────────────────────────
# Contractors
# ──────────────────────────────────────────────────────────────
def insert_contractor(record: Dict[str, Any]) -> int:
    """Upsert a contractor keyed by dedupe_key. Re-scraping the same business
    updates its row in place (same id) instead of creating a duplicate."""
    db = get_db()
    payload = {
        "business_name": record.get("business_name"),
        "city": record.get("city"),
        "zip_code": record.get("zip_code"),
        "address": record.get("address"),
        "tier": record.get("tier"),
        "specialty_keywords": record.get("specialty_keywords") or [],
        "google_categories": record.get("google_categories") or [],
        "services_listed": record.get("services_listed") or [],
        "phone": record.get("phone"),
        "email": record.get("email"),
        "website": record.get("website"),
        "owner_name": record.get("owner_name"),
        "license_status": record.get("license_status", "unknown"),
        "license_numbers": record.get("license_numbers") or [],
        "license_categories": record.get("license_categories") or [],
        "google_rating": record.get("google_rating"),
        "google_review_count": record.get("google_review_count"),
        "bbb_rating": record.get("bbb_rating"),
        "bbb_accredited": record.get("bbb_accredited"),
        "years_in_business": record.get("years_in_business"),
        "social_profiles": record.get("social_profiles") or {},
        "sources": record.get("sources") or [],
        "place_ids": record.get("place_ids") or [],
        "dedupe_key": compute_dedupe_key(record),
        "scraped_at": datetime.utcnow(),
        "job_id": record.get("job_id"),
    }
    saved = db.upsert("contractors", payload, unique_field="dedupe_key")
    return int(saved["id"])


def list_contractors(
    filters: Optional[Dict[str, Any]] = None,
    sort_by: str = "id",
    sort_dir: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """Filtered, sorted, paginated contractor list.

    `filters` keys (all optional, see api/routes/contractors.py for the shape):
      job_id, city[list], tier[list], license_status[list], search, business_name,
      zip_code, address, owner_name, bbb_rating,
      specialty_keywords, google_categories, services_listed,
      license_numbers, license_categories, sources, place_ids,
      has_email, has_phone, has_website, bbb_accredited,
      min_rating, min_review_count, min_years.
    """
    f = filters or {}
    rows = get_db().all_rows("contractors")
    rows = _filter_contractors(rows, f)

    reverse = (sort_dir or "desc").lower() != "asc"
    rows.sort(key=lambda r: _sort_key(r, sort_by), reverse=reverse)
    total = len(rows)
    page = rows[offset: offset + limit]
    return {"total": total, "limit": limit, "offset": offset, "rows": page}


def iter_contractors_filtered(
    filters: Optional[Dict[str, Any]] = None,
    sort_by: str = "id",
    sort_dir: str = "desc",
):
    """Streaming iterator for CSV export (no pagination)."""
    f = filters or {}
    rows = get_db().all_rows("contractors")
    rows = _filter_contractors(rows, f)
    reverse = (sort_dir or "desc").lower() != "asc"
    rows.sort(key=lambda r: _sort_key(r, sort_by), reverse=reverse)
    for r in rows:
        yield r


def get_contractor(contractor_id: int) -> Optional[Dict[str, Any]]:
    return get_db().get_by_id("contractors", contractor_id)


def contractor_facets(job_id: Optional[str] = None) -> Dict[str, Any]:
    rows = get_db().all_rows("contractors")
    if job_id:
        rows = [r for r in rows if r.get("job_id") == job_id]

    def _counts(field: str) -> List[Dict[str, Any]]:
        from collections import Counter
        c = Counter(r.get(field) for r in rows if r.get(field))
        return [{"value": v, "n": n} for v, n in c.most_common()]

    return {
        "total": len(rows),
        "cities": _counts("city"),
        "tiers": _counts("tier"),
        "license_statuses": _counts("license_status"),
    }


def get_contractor_classification(contractor_id: int) -> List[Dict[str, Any]]:
    contractor = get_db().get_by_id("contractors", contractor_id)
    if not contractor:
        return []
    place_ids = set(contractor.get("place_ids") or [])
    name = contractor.get("business_name")

    def _matches(r: Dict[str, Any]) -> bool:
        if r.get("contractor_id") == contractor_id:
            return True
        if r.get("place_id") and r["place_id"] in place_ids:
            return True
        if not place_ids and name and r.get("business_name") == name:
            return True
        return False

    rows = get_db().find("classification_log", _matches)
    rows.sort(key=lambda r: _dt_key(r.get("created_at")), reverse=True)
    return rows


def list_contractors_for_job(job_id: str) -> List[Dict[str, Any]]:
    """Used by dedupe.dedupe_all_for_job — return all rows for one job, ordered by id."""
    rows = get_db().find("contractors", lambda r: r.get("job_id") == job_id)
    rows.sort(key=lambda r: r.get("id") or 0)
    return rows


def update_contractor(contractor_id: int, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return get_db().update("contractors", contractor_id, fields)


def delete_contractors_by_ids(ids: List[int]) -> int:
    db = get_db()
    n = 0
    for cid in ids:
        if db.delete("contractors", cid):
            n += 1
    return n


# ──────────────────────────────────────────────────────────────
# Classification log
# ──────────────────────────────────────────────────────────────
def insert_classification_log(record: Dict[str, Any]) -> None:
    get_db().insert("classification_log", {
        "job_id": record.get("job_id"),
        "contractor_id": record.get("contractor_id"),
        "business_name": record.get("business_name"),
        "place_id": record.get("place_id"),
        "decision": record.get("decision"),
        "assigned_tier": record.get("assigned_tier"),
        "matched_keywords": record.get("matched_keywords") or [],
        "exclusion_keywords": record.get("exclusion_keywords") or [],
        "classifier_text": record.get("classifier_text", ""),
        "reason": record.get("reason", ""),
        "created_at": datetime.utcnow(),
    })


def insert_classification_logs(records: List[Dict[str, Any]], chunk_size: int = 1000) -> int:
    """Bulk insert. Background flusher batches the writes into Sheets calls."""
    if not records:
        return 0
    now = datetime.utcnow()
    payload = [{
        "job_id": r.get("job_id"),
        "contractor_id": r.get("contractor_id"),
        "business_name": r.get("business_name"),
        "place_id": r.get("place_id"),
        "decision": r.get("decision"),
        "assigned_tier": r.get("assigned_tier"),
        "matched_keywords": r.get("matched_keywords") or [],
        "exclusion_keywords": r.get("exclusion_keywords") or [],
        "classifier_text": r.get("classifier_text", ""),
        "reason": r.get("reason", ""),
        "created_at": now,
    } for r in records]
    inserted = get_db().bulk_insert("classification_log", payload)
    return len(inserted)


def list_classification_log(
    job_id: Optional[str] = None,
    decision: Optional[List[str]] = None,
    tier: Optional[List[str]] = None,
    search: Optional[str] = None,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    rows = get_db().all_rows("classification_log")
    if job_id:
        rows = [r for r in rows if r.get("job_id") == job_id]
    if decision:
        rows = [r for r in rows if r.get("decision") in decision]
    if tier:
        rows = [r for r in rows if r.get("assigned_tier") in tier]
    if search:
        s = search.lower()
        def _matches(r: Dict[str, Any]) -> bool:
            for f in ("business_name", "reason", "classifier_text"):
                v = r.get(f) or ""
                if s in str(v).lower():
                    return True
            return False
        rows = [r for r in rows if _matches(r)]

    reverse = (sort_dir or "desc").lower() != "asc"
    rows.sort(key=lambda r: (_sort_key(r, sort_by), -(r.get("id") or 0)), reverse=reverse)
    total = len(rows)
    return {"total": total, "limit": limit, "offset": offset, "rows": rows[offset: offset + limit]}


def classification_facets(job_id: Optional[str] = None) -> Dict[str, Any]:
    from collections import Counter
    rows = get_db().all_rows("classification_log")
    if job_id:
        rows = [r for r in rows if r.get("job_id") == job_id]

    decisions = Counter(r.get("decision") for r in rows if r.get("decision"))
    tiers = Counter(r.get("assigned_tier") for r in rows if r.get("assigned_tier"))
    return {
        "total": len(rows),
        "decisions": [{"value": v, "n": n} for v, n in decisions.most_common()],
        "tiers": [{"value": v, "n": n} for v, n in tiers.most_common()],
    }


def classification_stats(job_id: Optional[str] = None) -> Dict[str, Any]:
    from collections import Counter
    rows = get_db().all_rows("classification_log")
    if job_id:
        rows = [r for r in rows if r.get("job_id") == job_id]
    by_decision = dict(Counter(r.get("decision") for r in rows if r.get("decision")))
    tiers = Counter(r.get("assigned_tier") for r in rows if r.get("assigned_tier"))
    return {
        "by_decision": by_decision,
        "by_tier": [{"assigned_tier": t, "n": n} for t, n in tiers.most_common()],
    }


def get_classification_log(log_id: int) -> Optional[Dict[str, Any]]:
    return get_db().get_by_id("classification_log", log_id)


# ──────────────────────────────────────────────────────────────
# Keywords (used by classifier.py + API routes)
# ──────────────────────────────────────────────────────────────
def get_active_keywords() -> List[Dict[str, Any]]:
    rows = get_db().find("keywords", lambda r: r.get("active") is True)
    return [{"id": r.get("id"), "tier": r.get("tier"), "keyword": r.get("keyword")} for r in rows]


def list_keywords(tier: Optional[str] = None) -> List[Dict[str, Any]]:
    rows = get_db().all_rows("keywords")
    if tier:
        rows = [r for r in rows if r.get("tier") == tier]
        rows.sort(key=lambda r: (r.get("keyword") or "").lower())
    else:
        rows.sort(key=lambda r: ((r.get("tier") or ""), (r.get("keyword") or "").lower()))
    return rows


def get_keyword(keyword_id: int) -> Optional[Dict[str, Any]]:
    return get_db().get_by_id("keywords", keyword_id)


def keyword_facets() -> List[Dict[str, Any]]:
    from collections import Counter
    rows = get_db().all_rows("keywords")
    by_tier: Dict[str, Dict[str, int]] = {}
    for r in rows:
        t = r.get("tier")
        if not t:
            continue
        d = by_tier.setdefault(t, {"value": t, "n": 0, "n_active": 0})
        d["n"] += 1
        if r.get("active"):
            d["n_active"] += 1
    return sorted(by_tier.values(), key=lambda d: d["value"])


def insert_keyword_raw(tier: str, keyword: str, notes: Optional[str], created_by: str) -> Dict[str, Any]:
    """Insert a keyword. Returns the new row, or {} if (tier, keyword) duplicate."""
    db = get_db()
    keyword_lc = keyword.lower()
    if db.find_one("keywords", lambda r: r.get("tier") == tier and r.get("keyword") == keyword_lc):
        return {}
    now = datetime.utcnow()
    return db.insert("keywords", {
        "tier": tier,
        "keyword": keyword_lc,
        "active": True,
        "notes": notes,
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
    })


def update_keyword_raw(keyword_id: int, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return get_db().update("keywords", keyword_id, {**updates, "updated_at": datetime.utcnow()})


def delete_keyword_raw(keyword_id: int) -> bool:
    return get_db().delete("keywords", keyword_id)


def insert_keyword_change(record: Dict[str, Any]) -> Dict[str, Any]:
    return get_db().insert("keyword_changes", {
        "keyword_id": record.get("keyword_id"),
        "action": record.get("action"),
        "tier": record.get("tier"),
        "keyword": record.get("keyword"),
        "before_data": record.get("before_data"),
        "after_data": record.get("after_data"),
        "changed_by": record.get("changed_by"),
        "changed_at": datetime.utcnow(),
        "reason": record.get("reason"),
    })


def list_keyword_changes(keyword_id: int) -> List[Dict[str, Any]]:
    rows = get_db().find("keyword_changes", lambda r: r.get("keyword_id") == keyword_id)
    rows.sort(key=lambda r: _dt_key(r.get("changed_at")), reverse=True)
    return rows


# ──────────────────────────────────────────────────────────────
# DBPR licenses — see agent/dbpr_loader.py (in-memory DataFrame, not Sheets)
# ──────────────────────────────────────────────────────────────
def dbpr_license_count() -> int:
    from agent.dbpr_loader import dbpr_count
    return dbpr_count()


def query_dbpr_by_names(normalized_names: List[str]) -> List[Dict[str, Any]]:
    from agent.dbpr_loader import query_by_normalized_names
    return query_by_normalized_names(normalized_names)


# ──────────────────────────────────────────────────────────────
# App settings (key/value)
# ──────────────────────────────────────────────────────────────
DEFAULT_MAX_FINAL_RECORDS = 5000


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    row = get_db().get_by_id("app_settings", key)
    if not row:
        return default
    val = row.get("value")
    return val if val is not None else default


def set_setting(key: str, value: str) -> None:
    db = get_db()
    existing = db.get_by_id("app_settings", key)
    if existing:
        db.update("app_settings", key, {"value": str(value), "updated_at": datetime.utcnow()})
    else:
        db.insert("app_settings", {"key": key, "value": str(value), "updated_at": datetime.utcnow()})


def get_max_final_records() -> int:
    raw = get_setting("max_final_records")
    if raw is None:
        return DEFAULT_MAX_FINAL_RECORDS
    try:
        n = int(raw)
        return n if n > 0 else DEFAULT_MAX_FINAL_RECORDS
    except (TypeError, ValueError):
        return DEFAULT_MAX_FINAL_RECORDS


# ──────────────────────────────────────────────────────────────
# Users (auth)
# ──────────────────────────────────────────────────────────────
def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    return get_db().find_one("users", lambda r: r.get("email") == email)


def create_user(email: str, name: str, password_hash: str) -> Dict[str, Any]:
    db = get_db()
    if db.find_one("users", lambda r: r.get("email") == email):
        return {}
    return db.insert("users", {
        "email": email,
        "name": name,
        "password_hash": password_hash,
        "created_at": datetime.utcnow(),
    })


# ──────────────────────────────────────────────────────────────
# Cities + ZIPs (with zips inlined into each city row, like the old SQL view)
# ──────────────────────────────────────────────────────────────
def _city_with_zips(city: Dict[str, Any]) -> Dict[str, Any]:
    if not city:
        return city
    zips = get_db().find("city_zips", lambda r: r.get("city_id") == city.get("id"))
    zip_codes = sorted(z["zip_code"] for z in zips if z.get("zip_code"))
    return {**city, "zips": zip_codes}


def list_cities() -> List[Dict[str, Any]]:
    cities = get_db().all_rows("cities")
    cities.sort(key=lambda c: (c.get("name") or "").lower())
    return [_city_with_zips(c) for c in cities]


def get_city(city_id: int) -> Optional[Dict[str, Any]]:
    city = get_db().get_by_id("cities", city_id)
    return _city_with_zips(city) if city else None


def create_city(name: str, state: str, zips: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    db = get_db()
    if db.find_one("cities", lambda r: r.get("name") == name and r.get("state") == state):
        return None
    now = datetime.utcnow()
    city = db.insert("cities", {"name": name, "state": state, "created_at": now, "updated_at": now})
    for z in zips or []:
        zc = str(z).strip()
        if not zc:
            continue
        db.insert("city_zips", {"city_id": city["id"], "zip_code": zc, "created_at": now})
    return get_city(city["id"])


def update_city(city_id: int, name: Optional[str] = None, state: Optional[str] = None) -> Optional[Dict[str, Any]]:
    fields: Dict[str, Any] = {}
    if name is not None:
        fields["name"] = name
    if state is not None:
        fields["state"] = state
    if not fields:
        return get_city(city_id)
    fields["updated_at"] = datetime.utcnow()
    updated = get_db().update("cities", city_id, fields)
    return _city_with_zips(updated) if updated else None


def delete_city(city_id: int) -> bool:
    db = get_db()
    if not db.get_by_id("cities", city_id):
        return False
    # Cascade: remove all city_zips for this city, then the city itself.
    zips = db.find("city_zips", lambda r: r.get("city_id") == city_id)
    for z in zips:
        db.delete("city_zips", z["id"])
    return db.delete("cities", city_id)


def add_zip(city_id: int, zip_code: str) -> bool:
    db = get_db()
    if not db.get_by_id("cities", city_id):
        return False
    zc = zip_code.strip()
    if db.find_one("city_zips", lambda r: r.get("city_id") == city_id and r.get("zip_code") == zc):
        return False
    db.insert("city_zips", {"city_id": city_id, "zip_code": zc, "created_at": datetime.utcnow()})
    return True


def remove_zip(city_id: int, zip_code: str) -> bool:
    db = get_db()
    target = db.find_one("city_zips", lambda r: r.get("city_id") == city_id and r.get("zip_code") == zip_code.strip())
    if not target:
        return False
    return db.delete("city_zips", target["id"])


# ──────────────────────────────────────────────────────────────
# Health
# ──────────────────────────────────────────────────────────────
def ping() -> bool:
    """Cheap connectivity check — returns True if the spreadsheet is reachable."""
    try:
        get_db()
        return True
    except Exception as e:
        print(f"⚠️  ping() failed: {e}")
        return False


# ──────────────────────────────────────────────────────────────
# Internal filter / sort helpers (replaces the WHERE clause builder)
# ──────────────────────────────────────────────────────────────
_TEXT_COLS = ("business_name", "zip_code", "address", "owner_name", "bbb_rating")
_JSON_COLS = (
    "specialty_keywords", "google_categories", "services_listed",
    "license_numbers", "license_categories", "sources", "place_ids",
)


def _contains_ci(haystack: Any, needle: str) -> bool:
    if haystack is None:
        return False
    return needle.lower() in str(haystack).lower()


def _json_contains_ci(value: Any, needle: str) -> bool:
    if not value:
        return False
    if isinstance(value, (list, tuple)):
        return any(needle.lower() in str(v).lower() for v in value if v is not None)
    if isinstance(value, dict):
        return any(needle.lower() in str(v).lower() for v in value.values() if v is not None) \
            or any(needle.lower() in str(k).lower() for k in value.keys())
    return needle.lower() in str(value).lower()


def _filter_contractors(rows: List[Dict[str, Any]], f: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = rows

    job_id = f.get("job_id")
    if job_id:
        out = [r for r in out if r.get("job_id") == job_id]

    for field in ("city", "tier", "license_status"):
        vals = f.get(field)
        if vals:
            out = [r for r in out if r.get(field) in vals]

    if f.get("search"):
        s = f["search"].lower()
        out = [r for r in out if any(
            _contains_ci(r.get(col), s)
            for col in ("business_name", "phone", "email", "website", "address")
        )]

    for col in _TEXT_COLS:
        val = f.get(col)
        if val:
            out = [r for r in out if _contains_ci(r.get(col), val)]

    for col in _JSON_COLS:
        val = f.get(col)
        if val:
            out = [r for r in out if _json_contains_ci(r.get(col), val)]

    if f.get("has_email") is not None:
        if f["has_email"]:
            out = [r for r in out if r.get("email")]
        else:
            out = [r for r in out if not r.get("email")]
    if f.get("has_phone") is not None:
        if f["has_phone"]:
            out = [r for r in out if r.get("phone")]
        else:
            out = [r for r in out if not r.get("phone")]
    if f.get("has_website") is not None:
        if f["has_website"]:
            out = [r for r in out if r.get("website")]
        else:
            out = [r for r in out if not r.get("website")]

    if f.get("bbb_accredited") is not None:
        out = [r for r in out if bool(r.get("bbb_accredited")) == bool(f["bbb_accredited"])]

    if f.get("min_rating") is not None:
        out = [r for r in out if (r.get("google_rating") or 0) >= f["min_rating"]]
    if f.get("min_review_count") is not None:
        out = [r for r in out if (r.get("google_review_count") or 0) >= f["min_review_count"]]
    if f.get("min_years") is not None:
        out = [r for r in out if (r.get("years_in_business") or 0) >= f["min_years"]]

    return out


def _dt_key(value: Any) -> datetime:
    """Coerce a datetime cell to comparable naive-UTC.

    PG migration brought back TIMESTAMPTZ values as tz-aware datetimes; new
    writes via datetime.utcnow() are naive. Mixing them in sort() raises
    TypeError. Normalising at the comparison layer is the cheapest fix —
    every sort by *_at goes through here.
    """
    if value is None:
        return datetime.min
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
    # Fallback: ISO string from a half-decoded cell — try to parse, else push to min.
    try:
        s = str(value)
        dt = datetime.fromisoformat(s)
        return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
    except (TypeError, ValueError):
        return datetime.min


def _sort_key(row: Dict[str, Any], field: str) -> Any:
    """Tolerant of None — pushes None to one end consistently.
    Datetime fields are normalised to naive-UTC so tz-aware/tz-naive mixes
    don't blow up sort()."""
    v = row.get(field)
    if v is None:
        # Heterogeneous sort: sentinel that sorts last in DESC, first in ASC.
        return (1, "")
    if isinstance(v, datetime):
        return (0, _dt_key(v))
    if isinstance(v, str):
        # Strings that look like ISO datetimes get sorted as datetimes so a
        # mixed-tz tab still sorts coherently.
        if "T" in v and len(v) >= 10:
            try:
                return (0, _dt_key(v))
            except Exception:
                pass
        return (0, v.lower())
    return (0, v)
