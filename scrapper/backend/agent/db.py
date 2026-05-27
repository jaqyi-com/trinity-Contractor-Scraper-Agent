# db.py
# psycopg2 + raw SQL — production scraper pattern.
# Self-bootstrapping: CREATE TABLE IF NOT EXISTS runs on first connection.

import os
import json
import uuid
from typing import Optional, List, Dict, Any
from datetime import datetime

import threading

import psycopg2
import psycopg2.extensions
from psycopg2.extras import RealDictCursor, execute_values
from psycopg2 import pool as _pgpool
from dotenv import load_dotenv

load_dotenv()

POSTGRES_DSN = os.getenv("POSTGRES_DSN")
DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", "3"))   # pre-warmed conns for parallel page-load calls
DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "20"))


# ──────────────────────────────────────────────────────────────
# Connection POOL
# Opening a fresh Neon connection costs ~1.9s (remote + SSL handshake); the
# query itself is ~0.3s. So we pool connections and reuse them — every existing
# `conn = _get_conn(); ...; conn.close()` call now borrows/returns from the pool
# (the proxy's .close() returns it instead of really closing). ~5× faster GETs.
# ──────────────────────────────────────────────────────────────
_POOL = None
_POOL_LOCK = threading.Lock()


def _get_pool():
    global _POOL
    if _POOL is None:
        with _POOL_LOCK:
            if _POOL is None:
                if not POSTGRES_DSN:
                    raise RuntimeError("POSTGRES_DSN not set in .env")
                _POOL = _pgpool.ThreadedConnectionPool(DB_POOL_MIN, DB_POOL_MAX, POSTGRES_DSN)
    return _POOL


class _PooledConn:
    """Proxy around a pooled psycopg2 connection. Delegates everything, but
    .close() returns the connection to the pool instead of closing it, so all
    existing `conn.close()` call sites become pool-returns with no code change."""

    def __init__(self, conn, pool):
        self._conn = conn
        self._pool = pool

    def close(self):
        try:
            if self._conn.closed == 0:
                # Only rollback if a txn is actually open/aborted — skipping the
                # no-op rollback saves a network round-trip on read-only calls.
                if self._conn.info.transaction_status != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
                    try:
                        self._conn.rollback()
                    except Exception:
                        pass
                self._pool.putconn(self._conn)
            else:
                self._pool.putconn(self._conn, close=True)
        except Exception:
            try:
                self._conn.close()
            except Exception:
                pass

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __enter__(self):
        return self._conn.__enter__()

    def __exit__(self, *exc):
        return self._conn.__exit__(*exc)


def _get_conn():
    """Borrow a connection from the pool. Returns a proxy whose .close()
    returns it to the pool. Discards/replaces connections Neon has dropped."""
    pool = _get_pool()
    for _ in range(3):
        conn = pool.getconn()
        if conn.closed != 0:
            pool.putconn(conn, close=True)  # stale (Neon dropped it) — drop + retry
            continue
        return _PooledConn(conn, pool)
    # Last resort: a direct connection (won't be pooled)
    return psycopg2.connect(POSTGRES_DSN)


# ──────────────────────────────────────────────────────────────
# Schema bootstrap — runs once at startup
# ──────────────────────────────────────────────────────────────
def init_schema() -> None:
    """Create all tables if they don't exist. Idempotent."""
    conn = _get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id            UUID PRIMARY KEY,
                    status            TEXT NOT NULL,
                    current_stage     TEXT,
                    stages_progress   JSONB,
                    started_at        TIMESTAMPTZ DEFAULT NOW(),
                    finished_at       TIMESTAMPTZ,
                    error             TEXT,
                    keywords_snapshot JSONB
                );

                CREATE TABLE IF NOT EXISTS contractors (
                    id                   BIGSERIAL PRIMARY KEY,
                    business_name        TEXT NOT NULL,
                    city                 TEXT,
                    zip_code             TEXT,
                    address              TEXT,
                    tier                 TEXT,
                    specialty_keywords   JSONB,
                    google_categories    JSONB,
                    services_listed      JSONB,
                    phone                TEXT,
                    email                TEXT,
                    website              TEXT,
                    owner_name           TEXT,
                    license_status       TEXT,
                    license_numbers      JSONB,
                    license_categories   JSONB,
                    google_rating        REAL,
                    google_review_count  INTEGER,
                    bbb_rating           TEXT,
                    bbb_accredited       BOOLEAN,
                    years_in_business    INTEGER,
                    social_profiles      JSONB,
                    sources              JSONB,
                    place_ids            JSONB,
                    dedupe_key           TEXT,
                    scraped_at           TIMESTAMPTZ DEFAULT NOW(),
                    job_id               UUID REFERENCES jobs(job_id)
                );

                CREATE INDEX IF NOT EXISTS idx_contractors_city ON contractors(city);
                CREATE INDEX IF NOT EXISTS idx_contractors_tier ON contractors(tier);
                CREATE INDEX IF NOT EXISTS idx_contractors_phone ON contractors(phone);
                CREATE INDEX IF NOT EXISTS idx_contractors_job_id ON contractors(job_id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_contractors_dedupe_key ON contractors(dedupe_key);

                CREATE TABLE IF NOT EXISTS stage_outputs (
                    id         BIGSERIAL PRIMARY KEY,
                    job_id     UUID REFERENCES jobs(job_id),
                    stage_name TEXT,
                    row_index  INTEGER,
                    data       JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_stage_outputs_job_stage
                    ON stage_outputs(job_id, stage_name);

                CREATE TABLE IF NOT EXISTS keywords (
                    id          BIGSERIAL PRIMARY KEY,
                    tier        TEXT NOT NULL,
                    keyword     TEXT NOT NULL,
                    active      BOOLEAN DEFAULT TRUE,
                    notes       TEXT,
                    created_at  TIMESTAMPTZ DEFAULT NOW(),
                    updated_at  TIMESTAMPTZ DEFAULT NOW(),
                    created_by  TEXT DEFAULT 'system',
                    UNIQUE(tier, keyword)
                );

                CREATE INDEX IF NOT EXISTS idx_keywords_tier_active
                    ON keywords(tier, active);

                CREATE TABLE IF NOT EXISTS keyword_changes (
                    id          BIGSERIAL PRIMARY KEY,
                    keyword_id  BIGINT REFERENCES keywords(id) ON DELETE SET NULL,
                    action      TEXT NOT NULL,
                    tier        TEXT,
                    keyword     TEXT,
                    before_data JSONB,
                    after_data  JSONB,
                    changed_by  TEXT,
                    changed_at  TIMESTAMPTZ DEFAULT NOW(),
                    reason      TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_keyword_changes_keyword_id
                    ON keyword_changes(keyword_id);
                CREATE INDEX IF NOT EXISTS idx_keyword_changes_changed_at
                    ON keyword_changes(changed_at);

                CREATE TABLE IF NOT EXISTS classification_log (
                    id                  BIGSERIAL PRIMARY KEY,
                    job_id              UUID REFERENCES jobs(job_id),
                    contractor_id       BIGINT REFERENCES contractors(id) ON DELETE SET NULL,
                    business_name       TEXT,
                    place_id            TEXT,
                    decision            TEXT NOT NULL,
                    assigned_tier       TEXT,
                    matched_keywords    JSONB,
                    exclusion_keywords  JSONB,
                    classifier_text     TEXT,
                    reason              TEXT,
                    created_at          TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_classification_log_job_id
                    ON classification_log(job_id);
                CREATE INDEX IF NOT EXISTS idx_classification_log_decision
                    ON classification_log(decision);
                CREATE INDEX IF NOT EXISTS idx_classification_log_tier
                    ON classification_log(assigned_tier);

                CREATE TABLE IF NOT EXISTS users (
                    id            BIGSERIAL PRIMARY KEY,
                    email         TEXT NOT NULL UNIQUE,
                    name          TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at    TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS cities (
                    id         BIGSERIAL PRIMARY KEY,
                    name       TEXT NOT NULL,
                    state      TEXT NOT NULL DEFAULT 'FL',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(name, state)
                );

                CREATE TABLE IF NOT EXISTS city_zips (
                    id         BIGSERIAL PRIMARY KEY,
                    city_id    BIGINT NOT NULL REFERENCES cities(id) ON DELETE CASCADE,
                    zip_code   TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(city_id, zip_code)
                );

                CREATE INDEX IF NOT EXISTS idx_city_zips_city ON city_zips(city_id);

                CREATE TABLE IF NOT EXISTS dbpr_licenses (
                    id                  BIGSERIAL PRIMARY KEY,
                    license_number      TEXT,
                    occupation_code     TEXT,
                    licensee_name       TEXT,
                    dba_name            TEXT,
                    normalized_name     TEXT,
                    normalized_dba      TEXT,
                    primary_status      TEXT,
                    secondary_status    TEXT,
                    license_status      TEXT,
                    city                TEXT,
                    state               TEXT,
                    zip_code            TEXT,
                    original_issue_date TEXT,
                    expiration_date     TEXT,
                    refreshed_at        TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_dbpr_norm_name ON dbpr_licenses(normalized_name);
                CREATE INDEX IF NOT EXISTS idx_dbpr_norm_dba ON dbpr_licenses(normalized_dba);
            """)
        print("✅ DB schema initialized")
    finally:
        conn.close()

    # Bootstrap default data — idempotent (each function checks if empty first)
    _seed_test_user_if_missing()
    _seed_cities_from_yaml_if_empty()


# ──────────────────────────────────────────────────────────────
# Dedupe key — single canonical key per business for insert-time UPSERT.
# Priority mirrors PDF 3.4: normalized phone → domain → name + location.
# ──────────────────────────────────────────────────────────────
def compute_dedupe_key(record: Dict[str, Any]) -> str:
    from utils.phone_normalizer import normalize_phone
    from utils.url_normalizer import extract_domain
    from utils.name_normalizer import normalize_name

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
# Seed defaults — called from init_schema; safe to re-run
# ──────────────────────────────────────────────────────────────
def _seed_test_user_if_missing() -> None:
    """Ensure a test user exists. Email 'test@example.com', password '123456'."""
    from api.auth import hash_password

    conn = _get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE email = %s", ("test@example.com",))
            if cur.fetchone():
                return
            cur.execute(
                "INSERT INTO users (email, name, password_hash) VALUES (%s, %s, %s)",
                ("test@example.com", "Test User", hash_password("123456")),
            )
        print("✅ Seeded test user: test@example.com / 123456")
    finally:
        conn.close()


def _seed_cities_from_yaml_if_empty() -> None:
    """Load config/cities.yaml into cities + city_zips tables on first boot."""
    import yaml
    from pathlib import Path

    conn = _get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM cities")
            if cur.fetchone()[0] > 0:
                return

            yaml_path = Path(__file__).resolve().parent.parent / "config" / "cities.yaml"
            if not yaml_path.exists():
                print(f"⏩ No cities.yaml at {yaml_path} — skipping city seed")
                return

            data = yaml.safe_load(yaml_path.read_text())
            cities = data.get("cities", []) if isinstance(data, dict) else []
            total_zips = 0
            for c in cities:
                cur.execute(
                    """
                    INSERT INTO cities (name, state)
                    VALUES (%s, %s)
                    ON CONFLICT (name, state) DO NOTHING
                    RETURNING id
                    """,
                    (c.get("name"), c.get("state", "FL")),
                )
                row = cur.fetchone()
                if not row:
                    cur.execute(
                        "SELECT id FROM cities WHERE name = %s AND state = %s",
                        (c.get("name"), c.get("state", "FL")),
                    )
                    row = cur.fetchone()
                city_id = row[0]
                for z in c.get("zips", []) or []:
                    cur.execute(
                        """
                        INSERT INTO city_zips (city_id, zip_code)
                        VALUES (%s, %s)
                        ON CONFLICT (city_id, zip_code) DO NOTHING
                        """,
                        (city_id, str(z)),
                    )
                    total_zips += 1
        print(f"✅ Seeded {len(cities)} cities + {total_zips} ZIPs from cities.yaml")
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────
# Jobs
# ──────────────────────────────────────────────────────────────
def create_job() -> str:
    job_id = str(uuid.uuid4())
    conn = _get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO jobs (job_id, status) VALUES (%s, %s)",
                (job_id, "pending"),
            )
    finally:
        conn.close()
    return job_id


def update_job(job_id: str, **fields) -> None:
    """Update jobs row. Accepts status, current_stage, stages_progress, error, finished_at, keywords_snapshot."""
    if not fields:
        return

    # JSON-encode dict fields
    if "stages_progress" in fields and not isinstance(fields["stages_progress"], str):
        fields["stages_progress"] = json.dumps(fields["stages_progress"])
    if "keywords_snapshot" in fields and not isinstance(fields["keywords_snapshot"], str):
        fields["keywords_snapshot"] = json.dumps(fields["keywords_snapshot"])

    set_clauses = ", ".join(f"{k} = %s" for k in fields.keys())
    values = list(fields.values()) + [job_id]

    conn = _get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(f"UPDATE jobs SET {set_clauses} WHERE job_id = %s", values)
    finally:
        conn.close()


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    conn = _get_conn()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM jobs WHERE job_id = %s", (job_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def list_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    conn = _get_conn()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM jobs ORDER BY started_at DESC LIMIT %s",
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_running_job() -> Optional[Dict[str, Any]]:
    """
    Return the currently active job (status='pending' or 'running') if any.
    Used by /api/jobs/start to prevent duplicate concurrent runs,
    and by /api/jobs/current on frontend page-load to restore polling state.
    """
    conn = _get_conn()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM jobs
                WHERE status IN ('pending', 'running')
                ORDER BY started_at DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────
# Contractors
# ──────────────────────────────────────────────────────────────
def insert_contractor(record: Dict[str, Any]) -> int:
    """Upsert a contractor row keyed by dedupe_key (phone→domain→name+loc).
    Re-scraping the same business updates the existing row instead of creating
    a duplicate (PDF 1.4: single deduplicated master). Returns the row id."""
    dedupe_key = compute_dedupe_key(record)
    conn = _get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO contractors (
                    business_name, city, zip_code, address, tier,
                    specialty_keywords, google_categories, services_listed,
                    phone, email, website, owner_name,
                    license_status, license_numbers, license_categories,
                    google_rating, google_review_count,
                    bbb_rating, bbb_accredited, years_in_business,
                    social_profiles, sources, place_ids, dedupe_key, job_id
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s, %s
                )
                ON CONFLICT (dedupe_key) DO UPDATE SET
                    business_name      = EXCLUDED.business_name,
                    city               = EXCLUDED.city,
                    zip_code           = EXCLUDED.zip_code,
                    address            = EXCLUDED.address,
                    tier               = EXCLUDED.tier,
                    specialty_keywords = EXCLUDED.specialty_keywords,
                    google_categories  = EXCLUDED.google_categories,
                    services_listed    = EXCLUDED.services_listed,
                    phone              = EXCLUDED.phone,
                    email              = EXCLUDED.email,
                    website            = EXCLUDED.website,
                    owner_name         = EXCLUDED.owner_name,
                    license_status     = EXCLUDED.license_status,
                    license_numbers    = EXCLUDED.license_numbers,
                    license_categories = EXCLUDED.license_categories,
                    google_rating      = EXCLUDED.google_rating,
                    google_review_count= EXCLUDED.google_review_count,
                    bbb_rating         = EXCLUDED.bbb_rating,
                    bbb_accredited     = EXCLUDED.bbb_accredited,
                    years_in_business  = EXCLUDED.years_in_business,
                    social_profiles    = EXCLUDED.social_profiles,
                    sources            = EXCLUDED.sources,
                    place_ids          = EXCLUDED.place_ids,
                    scraped_at         = NOW(),
                    job_id             = EXCLUDED.job_id
                RETURNING id
                """,
                (
                    record.get("business_name"),
                    record.get("city"),
                    record.get("zip_code"),
                    record.get("address"),
                    record.get("tier"),
                    json.dumps(record.get("specialty_keywords") or []),
                    json.dumps(record.get("google_categories") or []),
                    json.dumps(record.get("services_listed") or []),
                    record.get("phone"),
                    record.get("email"),
                    record.get("website"),
                    record.get("owner_name"),
                    record.get("license_status", "unknown"),
                    json.dumps(record.get("license_numbers") or []),
                    json.dumps(record.get("license_categories") or []),
                    record.get("google_rating"),
                    record.get("google_review_count"),
                    record.get("bbb_rating"),
                    record.get("bbb_accredited"),
                    record.get("years_in_business"),
                    json.dumps(record.get("social_profiles") or {}),
                    json.dumps(record.get("sources") or []),
                    json.dumps(record.get("place_ids") or []),
                    dedupe_key,
                    record.get("job_id"),
                ),
            )
            return cur.fetchone()[0]
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────
# Classification log
# ──────────────────────────────────────────────────────────────
def insert_classification_log(record: Dict[str, Any]) -> None:
    conn = _get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO classification_log (
                    job_id, contractor_id, business_name, place_id,
                    decision, assigned_tier,
                    matched_keywords, exclusion_keywords,
                    classifier_text, reason
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s
                )
                """,
                (
                    record.get("job_id"),
                    record.get("contractor_id"),
                    record.get("business_name"),
                    record.get("place_id"),
                    record.get("decision"),
                    record.get("assigned_tier"),
                    json.dumps(record.get("matched_keywords") or []),
                    json.dumps(record.get("exclusion_keywords") or []),
                    record.get("classifier_text", ""),
                    record.get("reason", ""),
                ),
            )
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────
# Keywords (used by classifier.py + API routes)
# ──────────────────────────────────────────────────────────────
def get_active_keywords() -> List[Dict[str, Any]]:
    """Load all active keywords. Returns list of {tier, keyword} dicts."""
    conn = _get_conn()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, tier, keyword FROM keywords WHERE active = TRUE"
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def list_keywords(tier: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = _get_conn()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            if tier:
                cur.execute(
                    "SELECT * FROM keywords WHERE tier = %s ORDER BY keyword",
                    (tier,),
                )
            else:
                cur.execute("SELECT * FROM keywords ORDER BY tier, keyword")
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


# TODO: insert_keyword, update_keyword, delete_keyword, list_keyword_changes


# ──────────────────────────────────────────────────────────────
# DBPR licenses (bulk file — see agent/dbpr_loader.py)
# ──────────────────────────────────────────────────────────────
def dbpr_license_count() -> int:
    """Row count in dbpr_licenses — used to decide first-time bootstrap."""
    conn = _get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM dbpr_licenses")
            return cur.fetchone()[0]
    finally:
        conn.close()


def query_dbpr_by_names(normalized_names: List[str]) -> List[Dict[str, Any]]:
    """Return dbpr_licenses rows whose normalized name OR dba matches any input."""
    if not normalized_names:
        return []
    conn = _get_conn()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM dbpr_licenses
                WHERE normalized_name = ANY(%s) OR normalized_dba = ANY(%s)
                """,
                (normalized_names, normalized_names),
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def replace_dbpr_licenses(rows: List[tuple], chunk_size: int = 5000) -> int:
    """Full replace of the dbpr_licenses table. rows = list of value-tuples
    matching the INSERT column order below. Inserts in committed chunks so a
    single huge transaction doesn't get dropped by the Neon pooler."""
    from psycopg2.extras import execute_values

    insert_sql = """
        INSERT INTO dbpr_licenses (
            license_number, occupation_code, licensee_name, dba_name,
            normalized_name, normalized_dba, primary_status, secondary_status,
            license_status, city, state, zip_code,
            original_issue_date, expiration_date
        ) VALUES %s
    """

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE dbpr_licenses RESTART IDENTITY")
        conn.commit()

        inserted = 0
        for i in range(0, len(rows), chunk_size):
            chunk = rows[i:i + chunk_size]
            with conn.cursor() as cur:
                execute_values(cur, insert_sql, chunk, page_size=chunk_size)
            conn.commit()
            inserted += len(chunk)
        return inserted
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────
# Users (auth)
# ──────────────────────────────────────────────────────────────
def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    conn = _get_conn()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, email, name, password_hash, created_at FROM users WHERE email = %s",
                (email,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def create_user(email: str, name: str, password_hash: str) -> Dict[str, Any]:
    conn = _get_conn()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO users (email, name, password_hash)
                VALUES (%s, %s, %s)
                ON CONFLICT (email) DO NOTHING
                RETURNING id, email, name, created_at
                """,
                (email, name, password_hash),
            )
            row = cur.fetchone()
            return dict(row) if row else {}
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────
# Cities + ZIPs
# ──────────────────────────────────────────────────────────────
def list_cities() -> List[Dict[str, Any]]:
    """Return all cities with their zips inlined as a list."""
    conn = _get_conn()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT c.id, c.name, c.state, c.created_at, c.updated_at,
                       COALESCE(
                           ARRAY_AGG(z.zip_code ORDER BY z.zip_code) FILTER (WHERE z.zip_code IS NOT NULL),
                           ARRAY[]::TEXT[]
                       ) AS zips
                FROM cities c
                LEFT JOIN city_zips z ON z.city_id = c.id
                GROUP BY c.id
                ORDER BY c.name
                """
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_city(city_id: int) -> Optional[Dict[str, Any]]:
    conn = _get_conn()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT c.id, c.name, c.state, c.created_at, c.updated_at,
                       COALESCE(
                           ARRAY_AGG(z.zip_code ORDER BY z.zip_code) FILTER (WHERE z.zip_code IS NOT NULL),
                           ARRAY[]::TEXT[]
                       ) AS zips
                FROM cities c
                LEFT JOIN city_zips z ON z.city_id = c.id
                WHERE c.id = %s
                GROUP BY c.id
                """,
                (city_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def create_city(name: str, state: str, zips: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    """Create city; if name+state already exists, return None."""
    conn = _get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cities (name, state)
                VALUES (%s, %s)
                ON CONFLICT (name, state) DO NOTHING
                RETURNING id
                """,
                (name, state),
            )
            row = cur.fetchone()
            if not row:
                return None
            city_id = row[0]
            for z in zips or []:
                cur.execute(
                    """
                    INSERT INTO city_zips (city_id, zip_code)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (city_id, str(z).strip()),
                )
    finally:
        conn.close()
    return get_city(city_id)


def update_city(city_id: int, name: Optional[str] = None, state: Optional[str] = None) -> Optional[Dict[str, Any]]:
    fields = {}
    if name is not None:
        fields["name"] = name
    if state is not None:
        fields["state"] = state
    if not fields:
        return get_city(city_id)

    set_clause = ", ".join(f"{k} = %s" for k in fields)
    values = list(fields.values()) + [city_id]

    conn = _get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                f"UPDATE cities SET {set_clause}, updated_at = NOW() WHERE id = %s",
                values,
            )
            if cur.rowcount == 0:
                return None
    finally:
        conn.close()
    return get_city(city_id)


def delete_city(city_id: int) -> bool:
    conn = _get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("DELETE FROM cities WHERE id = %s", (city_id,))
            return cur.rowcount > 0
    finally:
        conn.close()


def add_zip(city_id: int, zip_code: str) -> bool:
    """Add a single ZIP to a city. Returns False if city doesn't exist or zip duplicate."""
    conn = _get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM cities WHERE id = %s", (city_id,))
            if not cur.fetchone():
                return False
            cur.execute(
                """
                INSERT INTO city_zips (city_id, zip_code)
                VALUES (%s, %s)
                ON CONFLICT (city_id, zip_code) DO NOTHING
                """,
                (city_id, zip_code.strip()),
            )
            return cur.rowcount > 0
    finally:
        conn.close()


def remove_zip(city_id: int, zip_code: str) -> bool:
    conn = _get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM city_zips WHERE city_id = %s AND zip_code = %s",
                (city_id, zip_code.strip()),
            )
            return cur.rowcount > 0
    finally:
        conn.close()
