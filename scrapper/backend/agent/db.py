# db.py
# Storage layer — Google Sheets (replaces psycopg2/Postgres).
#
# The public surface mirrors the old Postgres helpers byte-for-byte so callers
# (pipeline, processor, api/routes/*) don't change: same function names, same
# arguments, same return shapes. The bodies route through agent.sheets_client,
# which holds an in-memory mirror + batched write buffer + background flusher.
#
# DBPR licenses are NOT stored here — they are streamed from the official
# Florida CSV and match-filtered on demand (see dbpr_loader.py), so the 266k-row
# file never sits in memory.

import os
import time
import threading
import uuid
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from agent.sheets_client import get_db
from utils.phone_normalizer import normalize_phone
from utils.url_normalizer import extract_domain
from utils.name_normalizer import normalize_name

load_dotenv()


# ──────────────────────────────────────────────────────────────
# Runner mode — "thread" (pipeline runs in this process's background thread,
# the default for local dev) or "cloud_run_job" (pipeline runs in a separate
# Cloud Run Job container). In job mode the API service and the worker are
# different processes sharing the spreadsheet, so the service must read job
# state LIVE from Sheets instead of its stale in-RAM mirror.
# ──────────────────────────────────────────────────────────────
def _runner_is_job() -> bool:
    # Explicit override wins (set PIPELINE_RUNNER=thread to force in-process even
    # on Cloud Run, e.g. for debugging).
    explicit = os.getenv("PIPELINE_RUNNER")
    if explicit:
        return explicit.lower() == "cloud_run_job"
    # Auto-detect: Cloud Run injects K_SERVICE on services and CLOUD_RUN_EXECUTION
    # on jobs; our worker also gets JOB_ID. Any of these ⇒ we're on Cloud Run ⇒
    # use job mode. Locally none are set ⇒ thread mode. No env config needed.
    return bool(os.getenv("K_SERVICE") or os.getenv("CLOUD_RUN_EXECUTION") or os.getenv("JOB_ID"))


def _is_job_worker() -> bool:
    # The Cloud Run Job execution is launched with JOB_ID set (see agent/run_job.py).
    # The API service never has it. The worker is the jobs-tab writer, so it must
    # NOT reload that tab (it would clobber its own un-flushed progress).
    return bool(os.getenv("JOB_ID"))


_JOBS_RELOAD_INTERVAL = float(os.getenv("JOBS_RELOAD_INTERVAL", "2.0"))
_jobs_reload_at = 0.0
_jobs_reload_lock = threading.Lock()


def _refresh_jobs() -> None:
    """In Cloud Run Job mode, refresh the `jobs` mirror from Sheets so the API
    service sees the worker's live progress. Throttled, and only on the service
    side (never the worker — it owns the writes). No-op in thread mode."""
    if not _runner_is_job() or _is_job_worker():
        return
    global _jobs_reload_at
    now = time.monotonic()
    if now - _jobs_reload_at < _JOBS_RELOAD_INTERVAL:
        return
    with _jobs_reload_lock:
        if time.monotonic() - _jobs_reload_at < _JOBS_RELOAD_INTERVAL:
            return
        try:
            get_db().reload_tab("jobs")
            _jobs_reload_at = time.monotonic()
        except Exception as e:
            print(f"⚠️  [jobs] live reload failed (using cached): {e}")


# ──────────────────────────────────────────────────────────────
# Stop control — lives in the `job_control` tab, separate from `jobs`, so the
# service (stop writer) and worker (progress writer) never clobber each other.
# ──────────────────────────────────────────────────────────────
def request_job_stop(job_id: str) -> None:
    """Service-side: raise the stop flag and flush so the worker process sees it."""
    db = get_db()
    db.upsert("job_control", {
        "job_id": job_id,
        "stop_requested": True,
        "updated_at": datetime.utcnow(),
    }, unique_field="job_id")
    db.flush_all()  # make it visible to the worker (separate process) immediately


def clear_job_stop(job_id: str) -> None:
    """Worker-side: lower the stop flag once we've acted on it (paused)."""
    db = get_db()
    if db.get_by_id("job_control", job_id):
        db.update("job_control", job_id, {"stop_requested": False, "updated_at": datetime.utcnow()})


def is_stop_requested(job_id: str) -> bool:
    """Worker-side: has a stop been requested? Reads the control tab LIVE in job
    mode (the service is in another process); cheap — the tab is tiny."""
    db = get_db()
    if _runner_is_job():
        try:
            db.reload_tab("job_control")
        except Exception as e:
            print(f"⚠️  [job_control] live reload failed (using cached): {e}")
    row = db.get_by_id("job_control", job_id)
    return bool(row and row.get("stop_requested"))


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
    _seed_tennessee_cities_if_empty()
    _seed_tennessee_exclusions_if_empty()
    _seed_vendor_aliases_if_empty()
    _seed_negative_keywords_if_empty()
    _seed_budget_settings_if_missing()


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


# Fields that change every run regardless of real data changes — ignored when
# deciding new/updated/unchanged for the per-run result sheet. The Phase 1+ tag
# fields are metadata (not contractor data), so they're ignored too: this keeps
# existing Florida rows from spuriously re-versioning when the new columns appear.
_CHANGE_IGNORE_FIELDS = {
    "id", "dedupe_key", "scraped_at", "job_id",
    "client_id", "record_type", "state", "county", "city_tier",
    "canonical_entity_id", "out_of_territory", "excluded_reason",
    "enrichment_status", "is_big_box", "vendor_type", "canonical_network", "stage",
}


def _norm_for_diff(v: Any) -> Any:
    """Treat None / "" / [] / {} as the same 'empty' so cosmetic differences
    don't read as changes."""
    if v is None or v == "" or v == [] or v == {}:
        return None
    return v


def _contractor_changed(new: Dict[str, Any], existing: Dict[str, Any]) -> bool:
    """True if any meaningful field differs between a new contractor payload and
    the latest stored version (ignoring id/dedupe_key/scraped_at/job_id). Drives
    the versioned-insert decision in insert_contractor()."""
    for k, v in new.items():
        if k in _CHANGE_IGNORE_FIELDS:
            continue
        if _norm_for_diff(v) != _norm_for_diff(existing.get(k)):
            return True
    return False


# ──────────────────────────────────────────────────────────────
# Phase 1c — Entity resolution + idempotent upsert (staged-model load path)
#
# Stages (logical, raw-immutable): raw seeds → normalized → enriched →
# filtered/validated → deliverable. Raw is the discovery checkpoint (stage_outputs)
# and is never mutated; the contractors tab holds the canonical (resolved) layer.
#
# `compute_canonical_entity_id` resolves many SOURCE records (google, bbb, license,
# vendor branches) to ONE real business. `upsert_contractor` is the idempotent load:
# re-running a territory/source updates the canonical row instead of duplicating it.
# The legacy `insert_contractor` (versioned-by-batch) is untouched — the current
# Florida flow keeps using it; the pipeline switches over in a later phase.
# ──────────────────────────────────────────────────────────────
# List fields that accumulate provenance/detail across sources (union on merge).
_MERGE_LIST_FIELDS = (
    "sources", "place_ids", "specialty_keywords", "google_categories",
    "services_listed", "license_numbers", "license_categories",
)


def compute_canonical_entity_id(record: Dict[str, Any]) -> str:
    """Stable id for the real business behind one or more source records.
    Anchored on normalized NAME + LOCATION (or the canonical vendor network, when
    present, so GMS/L&W branches collapse). Phone is deliberately NOT in the hash:
    sources for the same business often differ on phone presence, and including it
    would split one business into several entities. Name is the stable anchor;
    phone-only matches (different name) are still caught by dedupe_key downstream."""
    name = normalize_name(record.get("canonical_network") or record.get("business_name") or "")
    loc = (record.get("zip_code") or record.get("city") or "").strip().lower()
    basis = f"{name}|{loc}" if name else f"phone:{normalize_phone(record.get('phone') or '')}"
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]
    return f"ce_{digest}"


def _merge_record(existing: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    """Merge a new source record into an existing canonical row: union the list
    fields, fill empty scalars (existing non-empty value wins so loads are stable/
    idempotent). Returns only the fields that actually changed."""
    changed: Dict[str, Any] = {}
    for k, v in new.items():
        if k in ("id", "canonical_entity_id", "dedupe_key"):
            continue
        if k in _MERGE_LIST_FIELDS:
            merged = list(dict.fromkeys([*(existing.get(k) or []), *(v or [])]))
            if merged != (existing.get(k) or []):
                changed[k] = merged
        elif _norm_for_diff(existing.get(k)) is None and _norm_for_diff(v) is not None:
            changed[k] = v
    return changed


def record_source(
    record: Dict[str, Any],
    source: str,
    run_id: Optional[str] = None,
    canonical_entity_id: Optional[str] = None,
    stage: str = "raw",
) -> Dict[str, Any]:
    """Append an immutable RAW snapshot of ONE source's view of a business to the
    `source_records` tab (append-only — never overwritten). Linked to its merged
    `contractors` row by canonical_entity_id (foreign key); the full payload is kept
    in `data` so nothing is lost. This is the raw layer + provenance log."""
    db = get_db()
    ceid = canonical_entity_id or record.get("canonical_entity_id") or compute_canonical_entity_id(record)
    return db.insert("source_records", {
        "canonical_entity_id": ceid,
        "record_type": record.get("record_type") or "contractor",
        "source": source,
        "scrape_run_id": run_id or record.get("job_id"),
        "business_name": record.get("business_name"),
        "phone": record.get("phone"),
        "city": record.get("city"),
        "zip_code": record.get("zip_code"),
        "website": record.get("website"),
        "data": record,
        "stage": stage,
        "created_at": datetime.utcnow(),
    })


def list_source_records(canonical_entity_id: str) -> List[Dict[str, Any]]:
    """All immutable per-source raw rows for one business (its full provenance),
    oldest first — drives the 'view this contractor's sources separately' feature."""
    rows = get_db().find("source_records", lambda r: r.get("canonical_entity_id") == canonical_entity_id)
    rows.sort(key=lambda r: r.get("id") or 0)
    return rows


# ── Workstream E — staged pipeline layers, named after the SCRAPER's ACTUAL
# pipeline phases (agent/pipeline.py PHASE_ORDER), not the doc's generic layer
# names. Each is a snapshot of the working set at that phase boundary:
#   discovery     → raw Google seeds
#   dedupe_seeds  → unique seeds (pre-enrichment dedupe)
#   classify      → tiered + lumber/territory-flagged
#   cap           → capped to max_final_records
#   enrich        → DBPR/BBB/Apollo-enriched + saved (the deliverable layer)
# (dedupe_final is a post-insert sweep — no new record set, so not snapshotted.) ──
STAGE_ORDER = ("discovery", "dedupe_seeds", "classify", "cap", "enrich")


def record_stage(job_id: str, stage: str, records, batch_name: Optional[str] = None,
                  record_type: Optional[str] = None) -> int:
    """Persist a snapshot of the record set at one pipeline stage for this batch.
    Append-only — each stage is a layer (Workstream E). Records may be pydantic
    models or dicts. `record_type` (e.g. 'vendor') is the run's type, used for early
    stages (discovery/dedupe) whose raw seeds don't carry record_type yet — so a
    vendor run's discovery snapshot is correctly tagged 'vendor', not 'contractor'."""
    db = get_db()
    if batch_name is None:
        job = get_job(job_id) or {}
        batch_name = job.get("name") or job_id
    now = datetime.utcnow()
    n = 0
    for r in records or []:
        rec = r.model_dump(mode="json") if hasattr(r, "model_dump") else dict(r)
        src = rec.get("source")
        if not src:
            srcs = rec.get("sources") or []
            src = srcs[0] if srcs else None
        db.insert("stage_records", {
            "batch": job_id,
            "batch_name": batch_name,
            "stage": stage,
            "record_type": rec.get("record_type") or record_type or "contractor",
            "canonical_entity_id": rec.get("canonical_entity_id") or compute_canonical_entity_id(rec),
            "state": rec.get("state"),
            "city": rec.get("city"),
            "city_tier": rec.get("city_tier"),
            "zip_code": rec.get("zip_code"),
            "source": src,
            "business_name": rec.get("business_name"),
            "phone": rec.get("phone"),
            "email": rec.get("email"),
            "website": rec.get("website"),
            "excluded_reason": rec.get("excluded_reason"),
            "data": rec,
            "created_at": now,
        })
        n += 1
    print(f"📚 [stage] {stage}: stored {n} records for batch {batch_name!r}")
    return n


def list_stage_batches() -> List[Dict[str, Any]]:
    """Distinct batches that have stage snapshots, each with per-stage row counts —
    drives the Pipeline Stages page's batch picker."""
    rows = get_db().all_rows("stage_records")
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        b = r.get("batch")
        if not b:
            continue
        e = out.setdefault(b, {"batch": b, "batch_name": r.get("batch_name"), "stages": {}, "max_id": 0})
        st = r.get("stage")
        e["stages"][st] = e["stages"].get(st, 0) + 1
        e["max_id"] = max(e["max_id"], r.get("id") or 0)
    return sorted(out.values(), key=lambda e: e["max_id"], reverse=True)


def list_stage_records(batch: str, stage: str, limit: int = 1000) -> List[Dict[str, Any]]:
    """Records stored at one (batch, stage), oldest first."""
    rows = get_db().find("stage_records", lambda r: r.get("batch") == batch and r.get("stage") == stage)
    rows.sort(key=lambda r: r.get("id") or 0)
    return rows[:limit]


def upsert_contractor(
    record: Dict[str, Any],
    source: Optional[str] = None,
    run_id: Optional[str] = None,
    stage: Optional[str] = None,
) -> int:
    """Idempotent load keyed on canonical_entity_id:
      • new entity      → insert ONE canonical row (canonical_entity_id + source set)
      • existing entity → merge into it (union lists, fill blanks, add source); no dup
    Re-running the same business/source is a no-op-or-update, never a duplicate.

    When `source` is given, this ALSO appends an immutable raw row to source_records
    (the per-source layer), so each scraper does two writes: raw snapshot + merged
    upsert. `stage` advances the canonical row's staged-model lifecycle."""
    db = get_db()
    rec = dict(record)
    ceid = rec.get("canonical_entity_id") or compute_canonical_entity_id(rec)
    rec["canonical_entity_id"] = ceid
    if source:
        rec["sources"] = list(dict.fromkeys([*(rec.get("sources") or []), source]))
        record_source(rec, source, run_id=run_id, canonical_entity_id=ceid, stage="raw")
    if stage:
        rec["stage"] = stage

    existing = db.find_one("contractors", lambda r: r.get("canonical_entity_id") == ceid)
    if existing:
        changed = _merge_record(existing, rec)
        if stage and existing.get("stage") != stage:
            changed["stage"] = stage          # let the lifecycle advance forward
        if changed:
            db.update("contractors", existing["id"], changed)
        return int(existing["id"])

    rec.setdefault("dedupe_key", compute_dedupe_key(rec))
    rec.setdefault("scraped_at", datetime.utcnow())
    saved = db.insert("contractors", rec)
    return int(saved["id"])


# ──────────────────────────────────────────────────────────────
# Seed defaults — called from init_schema; safe to re-run.
# ──────────────────────────────────────────────────────────────
def _seed_test_user_if_missing() -> None:
    """Ensure a test user exists. Email 'test@example.com', password '123456'."""
    db = get_db()
    existing = db.find_one("users", lambda r: r.get("email") == "test@example.com")
    if existing:
        print(f"🔎 [seed] test user already present (id={existing.get('id')}), skipping")
        return
    from api.auth import hash_password
    now = datetime.utcnow()
    db.insert("users", {
        "email": "test@example.com",
        "name": "Test User",
        "password_hash": hash_password("123456"),
        "created_at": now,
    })
    # Force a flush so the row hits Sheets before the first login request,
    # not 2s later when the background flusher next wakes.
    db.flush_all()
    print("✅ Seeded test user: test@example.com / 123456 (flushed)")


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


def _seed_tennessee_cities_if_empty() -> None:
    """Seed Tennessee cities into the SAME cities/city_zips tabs as Florida (first
    boot, idempotent — skips if any TN city already exists), so they're editable in
    the Cities UI exactly like FL and tagged state='TN'. Each TN city also carries
    tier + center coords + radius; its ZIPs are computed once (zips within the
    radius) so the list is real and user-editable. Florida rows are untouched."""
    import yaml
    from pathlib import Path
    from agent.geography import zips_within_radius

    db = get_db()
    if db.find_one("cities", lambda r: (r.get("state") or "").upper() == "TN"):
        return  # already seeded

    yaml_path = Path(__file__).resolve().parent.parent / "config" / "tennessee.yaml"
    if not yaml_path.exists():
        print(f"⏩ No tennessee.yaml at {yaml_path} — skipping TN city seed")
        return

    data = yaml.safe_load(yaml_path.read_text()) or {}
    state = data.get("state", "TN")
    cities = data.get("cities", []) if isinstance(data, dict) else []
    now = datetime.utcnow()
    total_zips = 0
    for c in cities:
        lat, lng = c.get("center_lat"), c.get("center_lng")
        radius = c.get("radius_miles") or 20
        city = db.insert("cities", {
            "name": c.get("city"),
            "state": state,
            "tier": c.get("tier"),
            "county": c.get("county"),
            "center_lat": lat,
            "center_lng": lng,
            "radius_miles": radius,
            "created_at": now,
            "updated_at": now,
        })
        zips = zips_within_radius(float(lat), float(lng), float(radius), state=state) if lat and lng else []
        for z in zips:
            db.insert("city_zips", {"city_id": city["id"], "zip_code": str(z), "created_at": now})
            total_zips += 1
    t1 = sum(1 for c in cities if c.get("tier") == 1)
    t2 = sum(1 for c in cities if c.get("tier") == 2)
    print(f"✅ Seeded {len(cities)} TN cities (Tier1={t1}, Tier2={t2}) + {total_zips} ZIPs into cities/city_zips")


def _seed_tennessee_exclusions_if_empty() -> None:
    """Seed the LOCKED Memphis-metro exclusion from tennessee.yaml on first boot
    (idempotent). Each rule stores the excluded city names AND their resolved ZIP
    codes (so the scraper drops them directly). `locked=True` → the user cannot edit
    or delete these base rules; they can only ADD more cities to exclude."""
    import yaml
    from pathlib import Path
    from agent.geography import zips_for_city

    db = get_db()
    if db.find_one("territories", lambda r: (r.get("state") or "").upper() == "TN"):
        return  # already seeded

    yaml_path = Path(__file__).resolve().parent.parent / "config" / "tennessee.yaml"
    if not yaml_path.exists():
        return

    data = yaml.safe_load(yaml_path.read_text()) or {}
    state = data.get("state", "TN")
    rules = data.get("exclusions", []) if isinstance(data, dict) else []
    now = datetime.utcnow()
    for r in rules:
        cities = r.get("match_values") or []
        zips = sorted({z for c in cities for z in zips_for_city(c, state)})
        db.insert("territories", {
            "state": state,
            "region_name": r.get("region_name"),
            "kind": r.get("kind", "exclude"),
            "match_type": "city",
            "match_values": cities,
            "zip_codes": zips,
            "locked": True,            # base rule — user can't remove
            "active": True,
            "notes": r.get("notes", ""),
            "created_at": now,
            "updated_at": now,
        })
    if rules:
        print(f"✅ Seeded {len(rules)} LOCKED TN exclusion rule(s) (Memphis metro) with resolved ZIPs")


def _seed_vendor_aliases_if_empty() -> None:
    """Load config/vendor_aliases.yaml into the vendor_aliases table on first boot
    (idempotent). Maps branch/brand names → one canonical network (GMS, L&W, …)."""
    import yaml
    from pathlib import Path

    db = get_db()
    if db.count("vendor_aliases") > 0:
        return

    yaml_path = Path(__file__).resolve().parent.parent / "config" / "vendor_aliases.yaml"
    if not yaml_path.exists():
        return

    data = yaml.safe_load(yaml_path.read_text()) or {}
    aliases = data.get("aliases", []) if isinstance(data, dict) else []
    now = datetime.utcnow()
    for a in aliases:
        db.insert("vendor_aliases", {
            "alias": a.get("alias"),
            "canonical_network": a.get("canonical_network"),
            "entity": a.get("entity"),
            "vendor_type": a.get("vendor_type", "specialty_distributor"),
            "active": True,
            "notes": "",
            "created_at": now,
            "updated_at": now,
        })
    if aliases:
        nets = len({a.get("canonical_network") for a in aliases})
        print(f"✅ Seeded {len(aliases)} vendor aliases ({nets} networks) from vendor_aliases.yaml")


def _seed_negative_keywords_if_empty() -> None:
    """Load config/negative_keywords.yaml into the negative_keywords table on first
    boot (idempotent). Feeds all 3 lumber-exclusion layers via the `layer` field."""
    import yaml
    from pathlib import Path

    db = get_db()
    if db.count("negative_keywords") > 0:
        return

    yaml_path = Path(__file__).resolve().parent.parent / "config" / "negative_keywords.yaml"
    if not yaml_path.exists():
        return

    data = yaml.safe_load(yaml_path.read_text()) or {}
    terms = data.get("terms", []) if isinstance(data, dict) else []
    now = datetime.utcnow()
    for t in terms:
        db.insert("negative_keywords", {
            "term": t.get("term"),
            "layer": t.get("layer", "keyword"),
            "is_regex": bool(t.get("is_regex", False)),
            "active": True,
            "notes": "",
            "created_at": now,
            "updated_at": now,
        })
    if terms:
        print(f"✅ Seeded {len(terms)} lumber negative-keyword terms from negative_keywords.yaml")


def is_excluded(
    city: Optional[str] = None,
    county: Optional[str] = None,
    zip_code: Optional[str] = None,
    state: Optional[str] = None,
) -> bool:
    """True if a location falls under an active territory EXCLUSION rule. Matches a
    ZIP directly against the rule's resolved zip_codes, OR a city name against its
    match_values (case-insensitive). Call BEFORE scraping so excluded cities/zips
    never cost a run."""
    z = (zip_code or "").strip()[:5]
    c = (city or "").strip().lower()
    for rule in get_territory_rules(state=state, kind="exclude"):
        if z and z in {str(x).strip() for x in (rule.get("zip_codes") or [])}:
            return True
        if c and c in {str(v).strip().lower() for v in (rule.get("match_values") or [])}:
            return True
    return False


# ── Exclusion list management (locked base + user-added cities) ──
def list_exclusions(state: Optional[str] = None) -> List[Dict[str, Any]]:
    """All active exclusion rules (locked base + user-added), for the UI list."""
    return get_territory_rules(state=state, kind="exclude")


def add_city_exclusion(city_name: str, state: str = "TN") -> Dict[str, Any]:
    """Add a user exclusion for a city (chosen from the cities dropdown). Resolves
    the city → its ZIPs so the scraper drops them directly. Not locked → deletable."""
    from agent.geography import zips_for_city
    now = datetime.utcnow()
    return get_db().insert("territories", {
        "state": state.upper(),
        "region_name": city_name,
        "kind": "exclude",
        "match_type": "city",
        "match_values": [city_name],
        "zip_codes": zips_for_city(city_name, state),
        "locked": False,
        "active": True,
        "notes": "user-added",
        "created_at": now,
        "updated_at": now,
    })


def delete_exclusion(rule_id: int) -> bool:
    """Delete a user exclusion. Refuses to remove a LOCKED base rule (Memphis)."""
    db = get_db()
    r = db.get_by_id("territories", rule_id)
    if not r:
        return False
    if r.get("locked"):
        raise ValueError("locked exclusion (base rule) cannot be deleted")
    return db.delete("territories", rule_id)


# ──────────────────────────────────────────────────────────────
# Jobs
# ──────────────────────────────────────────────────────────────
def create_job(mode: str = "contractor", territory: str = "FL") -> str:
    """Create a pending job. `mode` = contractor|vendor, `territory` = FL|TN.
    Defaults (contractor/FL) preserve the original Florida-contractor behaviour."""
    job_id = str(uuid.uuid4())
    db = get_db()
    # Each run gets a unique human-friendly batch name with its creation timestamp
    # ("Batch 1 · 2026-06-05 14:30 UTC") so the UI can tell runs apart at a glance.
    n = db.count("jobs") + 1
    now = datetime.utcnow()
    db.insert("jobs", {
        "job_id": job_id,
        "status": "pending",
        "started_at": now,
        "name": f"Batch {n} · {now:%Y-%m-%d %H:%M} UTC",
        "mode": (mode or "contractor").lower(),
        "territory": (territory or "FL").upper(),
    })
    # Flush so the row exists in Sheets before a Cloud Run Job worker (separate
    # process) boots and looks for it. Harmless in thread mode.
    db.flush_all()
    return job_id


def update_job(job_id: str, **fields) -> None:
    if not fields:
        return
    db = get_db()
    # Old Postgres code JSON-encoded these before passing through; now the sheets
    # encoder handles JSON serialisation, so we just hand the native dict in.
    db.update("jobs", job_id, fields)


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    _refresh_jobs()
    job = get_db().get_by_id("jobs", job_id)
    if job:
        # Surface the stop flag (control tab) on the job object for the frontend.
        ctrl = get_db().get_by_id("job_control", job_id)
        job["stop_requested"] = bool(ctrl and ctrl.get("stop_requested"))
    return job


def list_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    _refresh_jobs()
    rows = get_db().all_rows("jobs")
    rows.sort(key=lambda r: _dt_key(r.get("started_at")), reverse=True)
    return rows[:limit]


def get_running_job() -> Optional[Dict[str, Any]]:
    # "paused" is active-but-stopped: it still blocks a new /start (the user must
    # resume or cancel it first) and is surfaced to the frontend on mount.
    _refresh_jobs()
    rows = get_db().find("jobs", lambda r: r.get("status") in ("pending", "running", "paused"))
    if not rows:
        return None
    rows.sort(key=lambda r: _dt_key(r.get("started_at")), reverse=True)
    return rows[0]


# ──────────────────────────────────────────────────────────────
# Contractors
# ──────────────────────────────────────────────────────────────
def insert_contractor(record: Dict[str, Any], tab: str = "contractors") -> int:
    """Versioned save keyed by dedupe_key (into `tab`, default 'contractors';
    vendors save to 'vendors' via insert_vendor):
      • not in DB                 → insert a new row
      • in DB but data CHANGED    → insert a NEW row (new id + this run's job_id +
                                    fresh scraped_at) — the old version is kept
      • in DB and UNCHANGED       → no write (skip), return the existing id

    So the tab keeps a per-batch history of each business; filtering by job (batch)
    shows what that run added/changed."""
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
        # Phase 1+ tags — persisted so TN/vendor/territory/lumber metadata survives a
        # save. All ignored by change-detection (above), so Florida never re-versions.
        "client_id": record.get("client_id"),
        "record_type": record.get("record_type") or "contractor",
        "state": record.get("state"),
        "county": record.get("county"),
        "city_tier": record.get("city_tier"),
        "canonical_entity_id": record.get("canonical_entity_id") or compute_canonical_entity_id(record),
        "out_of_territory": bool(record.get("out_of_territory", False)),
        "excluded_reason": record.get("excluded_reason"),
        "enrichment_status": record.get("enrichment_status"),
        "is_big_box": bool(record.get("is_big_box", False)),
        "vendor_type": record.get("vendor_type"),
        "canonical_network": record.get("canonical_network"),
        "stage": record.get("stage"),
    }
    key = payload["dedupe_key"]
    existing = db.find(tab, lambda r: r.get("dedupe_key") == key)
    if existing:
        latest = max(existing, key=lambda r: r.get("id") or 0)
        if not _contractor_changed(payload, latest):
            return int(latest["id"])          # unchanged → skip
        # changed → fall through and insert a new version
    saved = db.insert(tab, payload)  # new id
    return int(saved["id"])


def insert_vendor(record: Dict[str, Any]) -> int:
    """Versioned save into the separate `vendors` tab (vendors are kept out of the
    contractors deliverable)."""
    return insert_contractor(record, tab="vendors")


def list_contractors(
    filters: Optional[Dict[str, Any]] = None,
    sort_by: str = "id",
    sort_dir: str = "desc",
    limit: int = 50,
    offset: int = 0,
    tab: str = "contractors",
) -> Dict[str, Any]:
    """Filtered, sorted, paginated business list from `tab` (default 'contractors';
    pass 'vendors' for the vendor list).

    `filters` keys (all optional, see api/routes/contractors.py for the shape):
      job_id, city[list], tier[list], license_status[list], search, business_name,
      zip_code, address, owner_name, bbb_rating,
      specialty_keywords, google_categories, services_listed,
      license_numbers, license_categories, sources, place_ids,
      has_email, has_phone, has_website, bbb_accredited,
      min_rating, min_review_count, min_years.
    """
    f = filters or {}
    rows = get_db().all_rows(tab)
    rows = _filter_contractors(rows, f)

    reverse = (sort_dir or "desc").lower() != "asc"
    rows.sort(key=lambda r: _sort_key(r, sort_by), reverse=reverse)
    total = len(rows)
    page = rows[offset: offset + limit]
    return {"total": total, "limit": limit, "offset": offset, "rows": page}


def list_vendors(filters=None, sort_by="id", sort_dir="desc", limit=50, offset=0) -> Dict[str, Any]:
    """Vendor list — same shape as list_contractors but from the separate vendors tab."""
    return list_contractors(filters, sort_by, sort_dir, limit, offset, tab="vendors")


def _deliverable_scope(rows: List[Dict[str, Any]], f: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Phase 1d — narrow the WIDE contractors layer into a deliverable view at
    request time (data is never filtered on disk):
      • scope by client_id / record_type / state(territory) / city_tier
      • by default DROP lumber-excluded (excluded_reason set) and out_of_territory
        rows — pass include_excluded / include_out_of_territory to audit them.
    record_type defaults to 'contractor' for legacy rows that predate the tag."""
    out = rows
    if f.get("client_id") is not None:
        out = [r for r in out if r.get("client_id") == f["client_id"]]
    if f.get("record_type") is not None:
        out = [r for r in out if (r.get("record_type") or "contractor") == f["record_type"]]
    if f.get("state"):
        st = f["state"].upper()
        out = [r for r in out if (r.get("state") or "").upper() == st]
    if f.get("city_tier") is not None:
        ct = str(f["city_tier"])
        out = [r for r in out if str(r.get("city_tier") or "") == ct]
    if not f.get("include_excluded"):
        out = [r for r in out if not r.get("excluded_reason")]
    if not f.get("include_out_of_territory"):
        out = [r for r in out if not r.get("out_of_territory")]
    return out


def export_deliverable(
    filters: Optional[Dict[str, Any]] = None,
    sort_by: str = "id",
    sort_dir: str = "desc",
) -> Dict[str, Any]:
    """Derived, client-/territory-scoped deliverable list (Phase 1d).
    Applies the same field filters as list_contractors (`filters` shape) PLUS the
    deliverable scope (client_id, record_type, state, city_tier, include_excluded,
    include_out_of_territory). Returns every matching row (no pagination) — meant
    for export/CRM sync. The underlying data stays wide; only this view narrows."""
    f = filters or {}
    rows = get_db().all_rows("contractors")
    rows = _filter_contractors(rows, f)      # reuse existing field filters
    rows = _deliverable_scope(rows, f)       # + derived deliverable narrowing
    reverse = (sort_dir or "desc").lower() != "asc"
    rows.sort(key=lambda r: _sort_key(r, sort_by), reverse=reverse)
    return {"total": len(rows), "rows": rows}


def iter_contractors_filtered(
    filters: Optional[Dict[str, Any]] = None,
    sort_by: str = "id",
    sort_dir: str = "desc",
    tab: str = "contractors",
):
    """Streaming iterator for CSV export (no pagination) from `tab`. This is the
    DELIVERABLE view: on top of the field filters it applies _deliverable_scope,
    which drops lumber-excluded (excluded_reason) and out_of_territory rows by
    default — so the exported list never contains flagged businesses (Workstream
    D/E). Pass include_excluded / include_out_of_territory in `filters` to audit."""
    f = filters or {}
    rows = get_db().all_rows(tab)
    rows = _filter_contractors(rows, f)      # field filters
    rows = _deliverable_scope(rows, f)       # + derived deliverable narrowing (drop flagged)
    reverse = (sort_dir or "desc").lower() != "asc"
    rows.sort(key=lambda r: _sort_key(r, sort_by), reverse=reverse)
    for r in rows:
        yield r


def iter_vendors_filtered(filters=None, sort_by="id", sort_dir="desc"):
    """Streaming vendor export iterator (from the vendors tab)."""
    return iter_contractors_filtered(filters, sort_by, sort_dir, tab="vendors")


def get_contractor(contractor_id: int, tab: str = "contractors") -> Optional[Dict[str, Any]]:
    return get_db().get_by_id(tab, contractor_id)


def get_vendor(vendor_id: int) -> Optional[Dict[str, Any]]:
    return get_db().get_by_id("vendors", vendor_id)


def contractor_facets(job_id: Optional[str] = None, tab: str = "contractors") -> Dict[str, Any]:
    rows = get_db().all_rows(tab)
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


def vendor_facets(job_id: Optional[str] = None) -> Dict[str, Any]:
    """Facet counts for the vendors tab (cities / vendor_type / canonical_network)."""
    rows = get_db().all_rows("vendors")
    if job_id:
        rows = [r for r in rows if r.get("job_id") == job_id]
    from collections import Counter

    def _counts(field: str):
        c = Counter(r.get(field) for r in rows if r.get(field))
        return [{"value": v, "n": n} for v, n in c.most_common()]

    return {
        "total": len(rows),
        "cities": _counts("city"),
        "vendor_types": _counts("vendor_type"),
        "networks": _counts("canonical_network"),
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
# DBPR licenses — see agent/dbpr_loader.py (streamed CSV match, not Sheets/memory)
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
# Per-run cost budgets (USD). None = unlimited (no cap).
# Discovery (Apify Maps) is enforced by Apify's native maxTotalChargeUsd;
# BBB/Apollo are enforced by us as a row-count cap (budget ÷ per-unit cost).
# ──────────────────────────────────────────────────────────────
def _get_budget_usd(key: str) -> Optional[float]:
    raw = get_setting(key)
    if raw is None or str(raw).strip().lower() in ("", "none", "unlimited"):
        return None
    try:
        v = float(raw)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def get_discovery_budget_usd() -> Optional[float]:
    return _get_budget_usd("discovery_budget_usd")


def get_bbb_budget_usd() -> Optional[float]:
    return _get_budget_usd("bbb_budget_usd")


def get_apollo_budget_usd() -> Optional[float]:
    return _get_budget_usd("apollo_budget_usd")


# ──────────────────────────────────────────────────────────────
# Search radii (miles) — user-editable (spec: vendor 20, contractor 50).
# Vendor radius anchors the vendor scrape on each city center; contractor radius
# anchors the TN contractor scrape on dealer accounts.
# ──────────────────────────────────────────────────────────────
DEFAULT_VENDOR_RADIUS_MI = 20.0
DEFAULT_CONTRACTOR_RADIUS_MI = 50.0


def _get_radius(key: str, default: float) -> float:
    raw = get_setting(key)
    try:
        v = float(raw)
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


def get_vendor_radius_miles() -> float:
    return _get_radius("vendor_radius_miles", DEFAULT_VENDOR_RADIUS_MI)


def get_contractor_radius_miles() -> float:
    return _get_radius("contractor_radius_miles", DEFAULT_CONTRACTOR_RADIUS_MI)


# ──────────────────────────────────────────────────────────────
# Boolean settings (stored as "true"/"false" strings in app_settings).
# ──────────────────────────────────────────────────────────────
def get_bool_setting(key: str, default: bool = False) -> bool:
    raw = get_setting(key)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def get_enable_tn_verify() -> bool:
    """OPTIONAL statewide TN verify-a-name license enrichment
    (verify.tn.gov / search.cloud.commerce.tn.gov). OFF by default — it's a slow
    per-name lookup (no bulk/public API), so it can add minutes to a TN run.
    License is enrichment-only; this never gates discovery. See agent/verify_tn.py."""
    return get_bool_setting("enable_tn_verify", default=False)


# Default for the budget settings on first boot: "none" = unlimited (no cap).
_BUDGET_SETTING_KEYS = ("discovery_budget_usd", "bbb_budget_usd", "apollo_budget_usd")


def _seed_budget_settings_if_missing() -> None:
    """Ensure the per-service cost-budget keys exist in app_settings. Idempotent —
    a key already present (any value) is left untouched; only missing keys are
    created with "none" (unlimited). Runs on every startup as a lightweight
    migration so the Settings UI always has these rows to read/write."""
    db = get_db()
    added = []
    for key in _BUDGET_SETTING_KEYS:
        if db.get_by_id("app_settings", key) is None:
            db.insert("app_settings", {"key": key, "value": "none",
                                       "updated_at": datetime.utcnow()})
            added.append(key)
    if added:
        db.flush_all()
        print(f"✅ [migrate] seeded budget settings (unlimited): {', '.join(added)}")
    else:
        print("🔎 [migrate] budget settings already present, skipping")


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
# Phase 1b — Reference tables (editable config, NOT scraped data)
# Generic CRUD over the new ref tabs + a few runtime convenience getters.
# ──────────────────────────────────────────────────────────────
_REF_TABS = {"territories", "city_tiers", "vendor_aliases", "negative_keywords", "dealer_accounts"}


def list_ref(tab: str, only_active: bool = False) -> List[Dict[str, Any]]:
    """Return all rows of a reference tab (optionally active-only)."""
    if tab not in _REF_TABS:
        raise ValueError(f"{tab} is not a reference table")
    rows = get_db().all_rows(tab)
    if only_active:
        rows = [r for r in rows if r.get("active") is True]
    return rows


def create_ref(tab: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Insert a reference row, stamping created_at/updated_at and defaulting active=True."""
    if tab not in _REF_TABS:
        raise ValueError(f"{tab} is not a reference table")
    now = datetime.utcnow()
    payload = {"active": True, **fields, "created_at": now, "updated_at": now}
    return get_db().insert(tab, payload)


def update_ref(tab: str, row_id: int, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if tab not in _REF_TABS:
        raise ValueError(f"{tab} is not a reference table")
    return get_db().update(tab, row_id, {**fields, "updated_at": datetime.utcnow()})


def delete_ref(tab: str, row_id: int) -> bool:
    if tab not in _REF_TABS:
        raise ValueError(f"{tab} is not a reference table")
    return get_db().delete(tab, row_id)


# ── Runtime convenience getters (used by the pipeline later) ──
def get_territory_rules(state: Optional[str] = None, kind: Optional[str] = None) -> List[Dict[str, Any]]:
    """Active territory include/exclude rules, optionally filtered by state/kind."""
    rows = list_ref("territories", only_active=True)
    if state:
        rows = [r for r in rows if (r.get("state") or "").upper() == state.upper()]
    if kind:
        rows = [r for r in rows if (r.get("kind") or "").lower() == kind.lower()]
    return rows


def list_city_tiers(state: Optional[str] = None) -> List[Dict[str, Any]]:
    """City-priority rows for targeting, read from the editable `cities` tab (so the
    UI and the scraper share ONE source of truth). Only cities that carry a tier +
    center coords qualify; sorted Tier 1 first, then by city. Each row is normalized
    to the {city, tier, center_lat, center_lng, radius_miles} shape targeting expects."""
    rows = get_db().all_rows("cities")
    if state:
        rows = [r for r in rows if (r.get("state") or "").upper() == state.upper()]
    out = [
        {
            "city": r.get("name"),
            "tier": r.get("tier"),
            "center_lat": r.get("center_lat"),
            "center_lng": r.get("center_lng"),
            "radius_miles": r.get("radius_miles"),
            "county": r.get("county"),
            "state": r.get("state"),
        }
        for r in rows
        if r.get("tier") is not None and r.get("center_lat") is not None and r.get("center_lng") is not None
    ]
    out.sort(key=lambda r: (r.get("tier") or 99, (r.get("city") or "").lower()))
    return out


def get_vendor_aliases() -> List[Dict[str, Any]]:
    """Active alias → canonical-network rows for vendor roll-up."""
    return list_ref("vendor_aliases", only_active=True)


def get_negative_keywords(layer: Optional[str] = None) -> List[Dict[str, Any]]:
    """Active lumber-exclusion terms, optionally for one filter layer."""
    rows = list_ref("negative_keywords", only_active=True)
    if layer:
        rows = [r for r in rows if (r.get("layer") or "").lower() == layer.lower()]
    return rows


def list_dealer_accounts(client_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Active dealer/vendor account anchors, optionally scoped to a client."""
    rows = list_ref("dealer_accounts", only_active=True)
    if client_id:
        rows = [r for r in rows if r.get("client_id") == client_id]
    return rows


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