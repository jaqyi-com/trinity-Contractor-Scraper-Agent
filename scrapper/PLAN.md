# Contractor Scraper Agent — Full Build Plan (Florida Lead Gen)

> Ye plan PDF `Contractor_Scraper_Agent_Spec_v2 (1).pdf` ke based pe banaya gaya hai. Goal: Florida ke 6 metros (Tampa, Orlando, Daytona Beach, Melbourne, Jacksonville, Gainesville) se drywall / GC / painter / remodeler / handyman businesses ka deduplicated, tier-tagged, license-status-tagged master list banana — React frontend pe **ek button** se trigger hoga, Python backend long-running pipeline chalayega (no timeout), DB me persist hoga, aur CSV/JSON export milega.
>
> **⚠️ Scope of this plan:** Ye **DEV / STAGING environment** ke liye hai. 100% FREE TIER — Vercel (frontend) + Render (backend) + Neon (PostgreSQL). Yahan code likho, test karo, demo dikhao.
>
> **Production deployment client ke saath decide hoga baad me.** Production ke liye Render Starter ($7/mo) ya GCP/AWS jo bhi client kahe, wahan migrate karenge — code same rahega, sirf hosting platform badlega. Saare design decisions production-portable hain (Postgres-based, Docker-friendly, stateless API).

---

## Context — Kya aur kyu

**Problem:** Client ko 6 Florida metros me drywall/GC/painter/handyman ke ~2000+ unique businesses chahiye outbound sales ke liye, har row pe:
- Tier (1/2/3 priority)
- License status (DBPR cross-referenced)
- Phone, email, website, owner name, BBB rating

**Why ye build:** Google Places API har query pe sirf 60 results deta hai aur email return nahi karta. DBPR alone se sirf licensed log milte hain — half industry unlicensed hai. BBB blocked rahta hai raw scrapers ke liye. Solution: **Outscraper (primary discovery) + Florida DBPR (license enrichment) + BBB actor (rating enrichment) + Apollo/Hunter (email enrichment)** ko ek sequential pipeline me chain karna.

**User experience:**
- React me **ek button** "Start Full Scrape" — click karte hi pipeline backend pe chalu
- Pipeline 2-6 hours chalti hai, **frontend timeout NAHI hoga** (polling pattern)
- Frontend pe live progress dikhega (kaun sa stage, kitne rows in/out)
- **Keywords UI me manage** — har tier ke keywords add/edit/delete kar sakta hai (DB me save)
- **Classification audit log** — har row pe "kyu add/remove hua" with matched keywords visible in UI
- **Proper multi-tab UI** — Dashboard / Keywords / Results / Logs / History tabs
- Final result DB me + downloadable CSV/JSON

**Output:** Master CSV + JSON + per-city CSV/JSON (6 metros × 2 = 12 files) + run log + full audit trail of every classification decision.

### Free Tier Architecture

```
┌──────────────────────────────────┐
│ React Frontend                   │
│ → Vercel (free, unlimited)       │  ← user clicks button
└────────────────┬─────────────────┘
                 │ HTTPS
                 ▼
┌──────────────────────────────────┐
│ FastAPI Backend                  │
│ → Render Free Web Service        │  ← /start, /status, /download
│ (handles BOTH API requests AND   │  ← pipeline runs as asyncio task
│  background pipeline in same     │     inside same process
│  process)                        │
└────────────────┬─────────────────┘
                 │
                 ▼
┌──────────────────────────────────┐
│ Neon PostgreSQL                  │
│ → Free tier (0.5GB, never        │  ← jobs + contractors + raw_*
│   expires)                       │
└──────────────────────────────────┘

       Render env vars → API keys (Outscraper, Apollo, Hunter, PDL)
       Render Disk (1GB free) → JSONL intermediate files + CSV exports
```

### Production Scraper Patterns We Adopt

> Reference: existing production-grade scraper at `/Users/apple/Desktop/we dev fortented/Scraping_code/` (portfolio company scraper). Hum **architecture & code patterns adopt karenge** — business logic UNCHANGED rahegi (Florida contractors, tiers, DBPR, BBB, etc.).

| # | Pattern | From production scraper | Applied to our build |
|---|---|---|---|
| 1 | **Flat module structure** | `pipeline.py`, `processor.py`, `scraper.py`, `deep_crawler.py`, `llm_extractor.py`, `db.py`, `schema.py` all at top level — no nested `stages/` folders | `agent/` folder is flat: `pipeline.py`, `processor.py`, `scraper_google.py`, `scraper_dbpr.py`, `scraper_bbb.py`, `classifier.py`, `matcher.py`, `dedupe.py`, `enrichment.py`, `exporter.py`, `db.py`, `schema.py` |
| 2 | **Pipeline + Processor split** | `pipeline.py` = orchestrator (loops over input URLs, manages writers, resume). `processor.py` = `process_portfolio_url(source_url)` does ALL 8 stages for ONE input | `pipeline.py` = job orchestrator (reads `jobs` row, manages CSV writers, updates progress). `processor.py` = `process_metro(city, job_id)` does discovery → classify → match → enrich for ONE city. Parallelizable later. |
| 3 | **psycopg2 + raw SQL** (not SQLAlchemy) | `db.py` uses `psycopg2.connect(DSN)`, `CREATE TABLE IF NOT EXISTS` inline, parameterized `%s` queries, single insert function per table | Same approach — `db.py` with `_get_conn()`, self-bootstrapping tables, `insert_contractor()`, `insert_classification_log()`, `update_job()` functions. Simpler than SQLAlchemy, matches prod. |
| 4 | **Pydantic schemas in single `schema.py`** | All data contracts in one file: `PageDoc`, `CompanySeed`, `PortfolioCsvRow` | Same — `schema.py` with `GoogleSeed`, `DBPRLicense`, `ContractorRow`, `ClassificationDecision`, `BBBEnrichment`, `EmailEnrichment` |
| 5 | **`utils/` folder for pure functions** | `utils/url_normalizer.py`, `utils/json_repair.py`, `utils/investor.py` | `utils/phone_normalizer.py`, `utils/address_normalizer.py`, `utils/url_normalizer.py`, `utils/name_normalizer.py` (no `json_repair.py` — that was LLM-only) |
| 6 | **Resume logic** | `load_processed_urls(output_file)` reads existing CSV → skip done items | Read `jobs` table → find `status='interrupted'` job → resume from `current_stage`. Each stage idempotent. |
| 7 | **`.env` + `python-dotenv`** | All secrets in `.env`, loaded at module top with `load_dotenv()` + `os.getenv()` | Same — `.env` locally (gitignored), Render env vars in production. Same env var names. |
| 8 | **Bounded payloads / API caps** | Production scraper caps inputs to control external API cost | Cap Outscraper calls per ZIP, DBPR pages, BBB lookups — same principle, prevents runaway API bills |
| 9 | **Bounded crawl** | `MAX_PAGES_PER_DOMAIN=800`, `MAX_DEPTH_PER_DOMAIN=6` | Cap DBPR Playwright pages, throttle 2-3s per request (PDF spec) |
| 10 | **try/except + traceback per item** | Every external call wrapped, failed items skip not crash | Same — each contractor row processed in isolation, errors logged to `classification_log` with reason |
| 11 | **Dual output** | CSV writer (streamed) + DB insert in same loop iteration | Same — write JSONL to disk + DB row + classification log entry in single iteration |
| 12 | **Bad-data reject lists** | `BAD_WEBSITE_KEYWORDS` for PE/VC aggregators (portfolio, fund, vc, crunchbase, linkedin) | Our hard-exclusion keywords (HVAC, asphalt, concrete, pool, pest, etc.) — same pattern, loaded from DB |
| 13 | **Print + emoji logging** | `print("🔍 Processing: ...")`, `print("💾 Saved: ...")`, `print("❌ Error: ...")` | Same style for stage progress. Render Logs dashboard captures stdout — no extra logger setup needed for v1. Loguru optional later. |
| ~~14~~ | ~~LLM dual-model pattern~~ | ~~Production scraper uses GPT~~ | **❌ NOT ADOPTED — we do not use LLM at all.** Our classifier is pure Python rule-based keyword matching. No OpenAI, no Anthropic, no Gemini. |
| 15 | **Sync wrappers around async** | `crawl_domain()` wraps `asyncio.run(_crawl_domain_async())` | Same for Playwright DBPR scraper — async internally, sync API for processor.py |
| 16 | **Idempotent inserts** | Same record can be re-saved without duplication | Use `ON CONFLICT (job_id, place_id) DO UPDATE` for contractor inserts |

**Bottom line:** We copy the **shape** of the production code (file layout, module boundaries, DB pattern, schema pattern, error handling, logging) but **fill it with our business logic** (Florida tiers, DBPR, BBB, dedupe rules, keywords CRUD, audit logging).

### Where Each Type of Config Lives (single source of truth — no duplication)

| Config | Where | Why |
|---|---|---|
| **Tier classifier keywords** (drywall, hvac, etc.) | `keywords` DB table | User-editable via Keywords UI tab; audit-logged in `keyword_changes` |
| **Outscraper subtype include/exclude filters** | **Derived from `keywords` DB table at runtime** in `scraper_google.py` | Same source as classifier — edit once, applies everywhere. No YAML duplication. |
| **Google search phrases** (e.g., "drywall contractor", "popcorn ceiling") | `DEFAULT_QUERIES` constant in `scraper_google.py` | Rarely edited; if user-editable needed later, add a `QUERY` tier to keywords table |
| **DBPR license categories** (Gypsum Drywall, CGC, CBC, …) | `LICENSE_CATEGORIES` constant in `scraper_dbpr.py` | Fixed by Florida law — never changes, never needs UI editing |
| **Cities + ZIP codes** | `config/cities.yaml` | Static infrastructure — 6 Florida metros + ~123 ZIPs |
| **API keys + DB DSN + paths** | `.env` (local) + Render env vars (production) | Secrets — never in code |

> **🚫 ZERO LLM in this project — ever.** No OpenAI, no Anthropic, no Gemini, no local LLMs. Hard rule.
>
> Why we don't need any: Outscraper / DBPR / BBB / Hunter / Apollo / PDL all return **structured JSON**. Our classifier is **rule-based keyword matching** (PDF Section 3.3 — `if "drywall" in text → TIER_1_DRYWALL`). Fuzzy matching uses `rapidfuzz` (deterministic string algos). Name normalization uses plain Python regex. Address parsing uses `usaddress`. **No reasoning step requires an LLM.**
>
> This means: no `OPENAI_API_KEY`, no `openai` Python package, no API cost per row, no LLM hallucination risk, no rate-limit retries, no temperature tuning. Pure deterministic pipeline.

---

### Free Tier Limitations & Workarounds (READ THIS)

| Limit | Impact | Mitigation |
|---|---|---|
| Render free service spins down after **15 min idle** | Pipeline asyncio task dies if no HTTP traffic | Frontend polls `/status` every 2s while job running → service never idle. Also self-ping every 10 min via internal asyncio loop. |
| Render free service has **750 hours/month** runtime | Enough for ~1 month always-on | OK for one user |
| Render free service has **cold start ~30 sec** | First button click after idle takes 30s | Acceptable for v1 |
| Render free **no background workers** | Can't have separate worker process | Pipeline runs INSIDE FastAPI process (async task) — fine for our use case |
| Render free **request timeout 100 sec** | `/start` request must return fast | Already designed — returns in <500ms with job_id |
| Neon free DB: **0.5GB storage** | Enough for ~10 full runs (~50MB per run) | Old jobs purge script after 1 month |
| Neon free DB: **auto-suspends after 5 min idle** | First query after idle = ~1s delay | Acceptable |
| Render free **ephemeral filesystem** | JSONL files lost on restart | Use Render Persistent Disk (1GB free) OR store intermediate JSONL in Postgres as JSONB |
| Vercel **free hobby plan** | Frontend only, no serverless needed | Perfect fit |

**Honest assessment for 6-hour pipelines on free tier:**
If user closes browser tab during a 6-hour run, polling stops → Render service goes idle after 15 min → spin down → pipeline dies. Mitigation: backend has internal "keep-alive" loop while job is running, OR we use `cron-job.org` (free) to ping `/health` every 10 min. Plan implements both.

---

## Stage-by-Stage Plan (Hinglish samjhaata hoon)

### Stage 0 — Credentials & Accounts Setup (Pehla din)

Ye **manual work** hai — code likhne se pehle saare API keys lena hai. Free trials pehle.

#### MUST HAVE — Third-party API keys (free trials available):

| Service | Purpose | Free tier / Trial | Signup |
|---|---|---|---|
| **Outscraper** | Google Maps + BBB scraping (PRIMARY) | $5-25 free credits on signup | outscraper.com → API tab → API Token |
| **Hunter.io** | Email finder from website domain | 25 searches/month FREE forever | hunter.io → Dashboard → API |
| **Apollo.io** | Owner name + LinkedIn enrichment | Free plan + 14-day paid trial | apollo.io → Settings → Integrations → API |
| **People Data Labs** (optional fallback) | Last-resort person enrichment | 100 free credits on signup | dashboard.peopledatalabs.com → API Keys |

#### MUST HAVE — Deployment platform accounts (all FREE):

| Service | Purpose | Free tier |
|---|---|---|
| **Vercel** | React frontend hosting | Unlimited static sites, 100GB bandwidth/month |
| **Render** | FastAPI backend | 750 hours/month free web service |
| **Neon** | PostgreSQL database | 0.5GB storage, never expires, autoscales |
| **GitHub** | Source code + auto-deploy trigger | Free unlimited public/private repos |

**Setup flow:**
1. Sign up at **vercel.com** with GitHub
2. Sign up at **render.com** with GitHub
3. Sign up at **neon.tech** → create project `contractor-scraper` → copy connection string
4. Sign up at **github.com** (agar account nahi hai)
5. Optional: **cron-job.org** free account for `/health` ping every 10 min (keep Render awake)

#### NO API KEY NEEDED:
- **Florida DBPR** (myfloridalicense.com) — Playwright scrape, public records under Sunshine Law
- **Google Maps** — Outscraper handles it
- **BBB** — Outscraper actor handles it

#### OPTIONAL (agar Outscraper reject ho jaye):
- **Apify** (alternative) — free $5/month credits

#### Cost estimate (free tier):
- **Infra:** $0/month (Vercel + Render + Neon all free)
- **Third-party APIs per full run:** ~$45-75 Outscraper + ~$5-15 BBB
- **Total monthly:** ~$50-90 only for scraping APIs

#### Credentials saare yahan store honge:
- **All API keys** → Render Environment Variables (Settings → Environment in Render dashboard)
- **DB connection string** → Render env var `DATABASE_URL`
- **Frontend env vars** → Vercel Environment Variables (`VITE_API_URL`)
- **Local dev `.env`** → gitignored, never committed

---

### Stage 1 — Project Skeleton (Day 1-2)

Folder structure banayenge:

```
contractor-scraper/
├── backend/
│   ├── agent/                          # FLAT structure (production scraper style)
│   │   ├── pipeline.py                 # Orchestrator — job loop, writers, resume, progress
│   │   ├── processor.py                # Per-metro processor — chains all stages for ONE city
│   │   ├── scraper_google.py           # Outscraper Google Maps (PRIMARY discovery)
│   │   ├── scraper_dbpr.py             # Playwright DBPR scraper (license enrichment)
│   │   ├── scraper_bbb.py              # Outscraper BBB actor (rating enrichment)
│   │   ├── classifier.py               # Tier classifier — loads keywords from DB, writes audit log
│   │   ├── matcher.py                  # Fuzzy match Google ↔ DBPR (rapidfuzz)
│   │   ├── dedupe.py                   # Phone/domain/name dedup helpers
│   │   ├── enrichment.py               # Email cascade: Hunter → Apollo → PDL
│   │   ├── exporter.py                 # CSV + JSON master + per-city files
│   │   ├── classification_logger.py    # Writes to classification_log table
│   │   ├── keywords.py                 # DB-loaded keyword store + CRUD helpers
│   │   ├── db.py                       # psycopg2 raw SQL (CREATE TABLE IF NOT EXISTS, inserts)
│   │   ├── schema.py                   # Pydantic models — all data contracts in ONE file
│   │   ├── storage.py                  # JSONL read/write on Render disk
│   │   ├── seed_keywords.py            # One-time PDF defaults → keywords table
│   │   └── run.py                      # CLI entry: python -m agent.run --full
│   ├── api/
│   │   ├── main.py                     # FastAPI app + CORS + lifespan
│   │   ├── routes/
│   │   │   ├── jobs.py                 # /jobs/start, /status, /download
│   │   │   ├── keywords.py             # CRUD + change history
│   │   │   ├── contractors.py          # Browse with filters
│   │   │   ├── classification.py       # Audit log endpoints
│   │   │   └── health.py               # /health + keep-alive
│   │   └── job_manager.py              # asyncio task management
│   ├── utils/                          # Pure functions only (production scraper pattern)
│   │   ├── phone_normalizer.py         # E.164 + strip non-digits + leading 1
│   │   ├── address_normalizer.py       # usaddress wrapper
│   │   ├── url_normalizer.py           # strip www, trailing slash, query — like prod scraper
│   │   ├── name_normalizer.py          # lowercase, strip punctuation, expand abbreviations
│   │   └── (no json_repair.py — that was LLM-only, removed)
│   ├── config/
│   │   └── cities.yaml                 # ONLY metros + ZIPs (truly static infra)
│   ├── requirements.txt
│   ├── render.yaml                     # Render Blueprint
│   ├── start.sh                        # uvicorn launch
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── App.tsx                     # Sidebar layout + router
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx           # Tab 1
│   │   │   ├── Keywords.tsx            # Tab 2
│   │   │   ├── Results.tsx             # Tab 3
│   │   │   ├── Logs.tsx                # Tab 4
│   │   │   └── History.tsx             # Tab 5
│   │   ├── components/
│   │   │   ├── Sidebar.tsx
│   │   │   ├── ProgressPanel.tsx
│   │   │   ├── KeywordDialog.tsx
│   │   │   ├── KeywordTable.tsx
│   │   │   ├── ContractorTable.tsx
│   │   │   ├── ContractorDrawer.tsx
│   │   │   └── ui/                     # shadcn components
│   │   ├── lib/
│   │   │   ├── api.ts
│   │   │   └── queries.ts              # react-query hooks
│   │   └── types/
│   │       └── api.ts                  # TypeScript types matching backend
│   ├── package.json
│   ├── tailwind.config.ts
│   ├── vite.config.ts
│   ├── vercel.json
│   └── .env.example                    # VITE_API_URL=...
└── README.md
```

**Tech choices (free tier-aware + production scraper aligned):**
- **Backend:** Python 3.11 + FastAPI
- **DB driver:** `psycopg2-binary` + **raw SQL** (matches production scraper — no ORM overhead). Connection via `os.getenv("POSTGRES_DSN")`, `CREATE TABLE IF NOT EXISTS` inline.
- **DB:** Neon PostgreSQL (free tier)
- **Schema validation:** `pydantic>=2` (single `schema.py` with all models — production scraper pattern)
- **Long-running:** FastAPI `asyncio.create_task()` background task inside same process
- **Frontend:** React + Vite + TypeScript → Vercel
- **Live progress:** Frontend polls `/status/{job_id}` every 2 seconds
- **Storage:** Render Persistent Disk (1GB free) for JSONL files, with Postgres JSONB fallback for redundancy
- **Secrets:** `python-dotenv` locally + Render env vars in production (production scraper uses same pattern)
- **Scraping libs:**
  - **Outscraper Python SDK** — Google Maps + BBB (primary)
  - **Playwright** (headless Chromium) — DBPR scraping with 2-3s throttle
  - **rapidfuzz** — fuzzy name matching (token_set_ratio ≥ 88/90)
  - **phonenumbers** — E.164 normalization
  - **usaddress** — address parsing
- **Logging:** `print()` with emoji prefixes (🔍 ⚙️ ✅ ❌ 💾) → stdout → Render Logs dashboard. Matches production scraper. Loguru optional later.
- **HTTP client:** `requests` (sync) for Outscraper/Hunter/Apollo/PDL APIs

---

### Stage 2 — Timeout Problem Solve Karna (Day 2 — MOST IMPORTANT)

Ye sabse critical hai. Pipeline 2-6 hours chalti hai. Browser HTTP request 30-60 sec me timeout maarta hai. Render free service request timeout 100 sec hai. Solve karne ka tareeka:

**Pattern: "Fire and Forget + Poll for Status"**

```
[User clicks button]
     │ POST /api/start
     ▼
[FastAPI on Render] ── 200 OK with {job_id} in <500ms ──→ [Frontend]
     │
     │ asyncio.create_task(run_pipeline(job_id))
     ▼
[Background asyncio task runs 2-6 hours INSIDE same process]
     │ updates `jobs` row in Neon DB after each stage
     ▼
[Neon Postgres]
     ▲
     │ polls /status/{job_id} every 2s
[Frontend] ←─── status JSON ───
```

**Step by step:**

1. React button click → POST `/api/start` to Render
2. Backend generates `job_id` UUID, inserts `jobs` row (status='pending')
3. Backend kicks off `asyncio.create_task(run_pipeline(job_id))` — task runs in background, request returns immediately
4. Backend returns `{job_id, status: 'pending'}` in <500ms (well under Render's 100s request timeout)
5. Pipeline asyncio task runs 8 stages, updates `jobs` table after each stage
6. Frontend polls `GET /api/status/{job_id}` every 2 seconds
7. **As long as polling happens, Render service stays awake** (idle counter resets on every request)
8. Pipeline completes → writes CSV/JSON to disk + DB → frontend gets `status='completed'`
9. Download buttons hit `/api/download/{job_id}/{filename}` → streams file response

**Keep-alive safety nets (because Render free spins down after 15 min idle):**
- **Safety net 1:** Frontend polls every 2s while job running → service stays awake
- **Safety net 2:** Internal asyncio "self-ping" loop — backend pings its own `/health` every 10 min while any job is running
- **Safety net 3:** Optional external ping via `cron-job.org` (free) hitting `/health` every 10 min — covers case when user closes browser tab

**State recovery (if Render restarts mid-pipeline):**
- Each stage writes output to Render Persistent Disk JSONL + Neon DB JSONB
- On startup, backend checks for jobs in `status='running'` whose `current_stage` is mid-flight
- Sets them to `status='interrupted'` — frontend shows "Resume from stage X" button
- User can resume — pipeline picks up from last completed stage

**Why this works on free tier:**
- ✅ HTTP `/start` request finishes in ms (well under 100s timeout)
- ✅ asyncio task runs in background indefinitely (no per-request timeout once kicked off)
- ✅ Polling keeps service awake
- ✅ Frontend never holds a long connection
- ⚠️ Worst case: Render restart during run → frontend offers resume

---

### Stage 3 — Database Schema (Day 2)

**Neon PostgreSQL** use karenge with **psycopg2 + raw SQL** (production scraper pattern, no ORM). `db.py` me self-bootstrapping `CREATE TABLE IF NOT EXISTS` blocks — first connection pe tables auto-create ho jaate hain. Schema PDF Section 5 + naye additions (keywords + audit log):

```sql
-- 1. Jobs table — har full-pipeline run track karne ke liye
CREATE TABLE jobs (
  job_id          UUID PRIMARY KEY,
  status          TEXT NOT NULL,          -- 'pending' | 'running' | 'completed' | 'failed' | 'interrupted'
  current_stage   TEXT,                   -- e.g. 'stage3_classify'
  stages_progress JSONB,                  -- {stage1: {rows_in, rows_out, status}, ...}
  started_at      TIMESTAMPTZ DEFAULT NOW(),
  finished_at     TIMESTAMPTZ,
  error           TEXT,
  -- Snapshot of keywords used at job start time (for reproducibility/audit)
  keywords_snapshot JSONB
);

-- 2. Contractors table — final master data (matches PDF Section 5 schema)
CREATE TABLE contractors (
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
  scraped_at           TIMESTAMPTZ DEFAULT NOW(),
  job_id               UUID REFERENCES jobs(job_id)
);

CREATE INDEX idx_contractors_city ON contractors(city);
CREATE INDEX idx_contractors_tier ON contractors(tier);
CREATE INDEX idx_contractors_phone ON contractors(phone);
CREATE INDEX idx_contractors_job_id ON contractors(job_id);

-- 3. Stage outputs as JSONB (fallback to disk JSONL)
CREATE TABLE stage_outputs (
  id         BIGSERIAL PRIMARY KEY,
  job_id     UUID REFERENCES jobs(job_id),
  stage_name TEXT,
  row_index  INTEGER,
  data       JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_stage_outputs_job_stage ON stage_outputs(job_id, stage_name);

-- 4. KEYWORDS table — user-managed via UI (CRUD)
CREATE TABLE keywords (
  id          BIGSERIAL PRIMARY KEY,
  tier        TEXT NOT NULL,              -- 'TIER_1_DRYWALL' | 'TIER_1_GC' | 'TIER_2_PAINTER' |
                                          -- 'TIER_2_REMODELER' | 'TIER_3_HANDYMAN' |
                                          -- 'EXCLUDE_HARD' | 'EXCLUDE_SOLO'
  keyword     TEXT NOT NULL,              -- lowercased phrase, e.g. "drywall", "popcorn ceiling"
  active      BOOLEAN DEFAULT TRUE,
  notes       TEXT,                       -- optional: "added for sheetrock variants" etc.
  created_at  TIMESTAMPTZ DEFAULT NOW(),
  updated_at  TIMESTAMPTZ DEFAULT NOW(),
  created_by  TEXT,                       -- 'system' (seed) or user email
  UNIQUE(tier, keyword)
);

CREATE INDEX idx_keywords_tier_active ON keywords(tier, active);

-- 5. KEYWORD CHANGE LOG — audit who changed what when
CREATE TABLE keyword_changes (
  id          BIGSERIAL PRIMARY KEY,
  keyword_id  BIGINT REFERENCES keywords(id) ON DELETE SET NULL,
  action      TEXT NOT NULL,              -- 'CREATE' | 'UPDATE' | 'DELETE' | 'ACTIVATE' | 'DEACTIVATE'
  tier        TEXT,                       -- snapshot at change time
  keyword     TEXT,                       -- snapshot
  before_data JSONB,                      -- previous state (for UPDATE/DELETE)
  after_data  JSONB,                      -- new state (for CREATE/UPDATE)
  changed_by  TEXT,
  changed_at  TIMESTAMPTZ DEFAULT NOW(),
  reason      TEXT                        -- optional user-provided reason
);

CREATE INDEX idx_keyword_changes_keyword_id ON keyword_changes(keyword_id);
CREATE INDEX idx_keyword_changes_changed_at ON keyword_changes(changed_at);

-- 6. CLASSIFICATION AUDIT LOG — har row ka "why include/exclude" trace
CREATE TABLE classification_log (
  id                  BIGSERIAL PRIMARY KEY,
  job_id              UUID REFERENCES jobs(job_id),
  contractor_id       BIGINT REFERENCES contractors(id) ON DELETE SET NULL,
  -- Identity (so log survives even if contractor row gets dedupe-merged)
  business_name       TEXT,
  place_id            TEXT,
  -- Decision
  decision            TEXT NOT NULL,        -- 'INCLUDED' | 'EXCLUDED'
  assigned_tier       TEXT,                 -- TIER_1_DRYWALL etc., OR 'EXCLUDE'
  -- Why this decision
  matched_keywords    JSONB,                -- [{tier: 'TIER_1_DRYWALL', keyword: 'drywall'}, ...]
  exclusion_keywords  JSONB,                -- keywords from EXCLUDE that hit
  classifier_text     TEXT,                 -- the full combined text classifier scanned
  reason              TEXT,                 -- human-readable: "Matched TIER_1_DRYWALL keyword 'sheetrock'"
  created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_classification_log_job_id ON classification_log(job_id);
CREATE INDEX idx_classification_log_decision ON classification_log(decision);
CREATE INDEX idx_classification_log_tier ON classification_log(assigned_tier);
CREATE INDEX idx_classification_log_contractor ON classification_log(contractor_id);
```

**Seed data:** On first deploy, seed `keywords` table from PDF Section 1.2 + 3.3 (all the tier keyword lists). After that, user manages via UI.

**Neon setup:**
- Sign up neon.tech → create project `contractor-scraper`
- Default branch `main` ka connection string copy karna hai
- Format: `postgresql://user:pass@host.neon.tech/contractor-scraper?sslmode=require`
- Set as `DATABASE_URL` env var in Render

**File storage (Render Persistent Disk):**
```
/var/data/jobs/
  └── {job_id}/
      ├── stage1_google.jsonl
      ├── ... (all stages)
      └── exports/
          ├── contractors_florida_master.csv
          ├── contractors_florida_master.json
          └── contractors_{city}.{csv,json}  (12 files)
```

**Storage redundancy:** JSONL files **also** mirrored to `stage_outputs` table in Postgres — so if Render disk wiped, can rebuild from DB.

---

### Stage 4 — Backend Pipeline (Day 3-7 — meat of the work)

**Architecture: Pipeline + Processor split (production scraper pattern)**

```
pipeline.py  ──── orchestrator ──────────────────────────────────
   │  reads jobs row, manages CSV writers, resume logic, error envelope
   │
   ▼  for each metro in cities.yaml:
processor.py ──── process_metro(city, job_id) ────────────────────
   │  chains all 8 stages for ONE city → returns metro_summary
   │
   ▼
   scraper_google.py    →  ContractorRow seeds (from Outscraper)
   scraper_dbpr.py      →  DBPRLicense list (Playwright, cached)
   classifier.py        →  Tier assignment + ClassificationDecision
   classification_logger.py  →  writes audit log entry per row
   matcher.py           →  fuzzy match seeds ↔ DBPR licenses
   dedupe.py            →  phone/domain/name dedup
   scraper_bbb.py       →  BBB enrichment per row
   enrichment.py        →  email cascade (Hunter → Apollo → PDL)
   exporter.py          →  CSV + JSON master + per-city
```

Each module exposes ONE primary function (production scraper convention):
- `scraper_google.py` → `scrape_metro(city, zips) -> List[GoogleSeed]` — queries default to `DEFAULT_QUERIES` constant, Outscraper subtype include/exclude **derived from `keywords` DB table at runtime** (no YAML duplication)
- `scraper_dbpr.py` → `fetch_licenses(categories) -> List[DBPRLicense]`
- `classifier.py` → `classify(row, keywords) -> ClassificationDecision`
- `matcher.py` → `match_license(seed, dbpr_index) -> Optional[DBPRLicense]`
- `dedupe.py` → `dedupe(rows) -> List[ContractorRow]`
- `scraper_bbb.py` → `enrich_bbb(row) -> BBBEnrichment`
- `enrichment.py` → `enrich_email(row) -> EmailEnrichment`
- `exporter.py` → `export_all(job_id, contractors) -> ExportPaths`

**Per-stage details (PDF Section 3.1 + business logic UNCHANGED):**

#### Stage 1: Google Discovery (`scraper_google.py`)
- Loop: `for city in cities → for zip in city.zips → for query in queries → call_outscraper(...)`
- Queries (PDF 2.1): `drywall contractor`, `drywall repair`, `drywall texturing`, `sheetrock contractor`, `plasterer`, `popcorn ceiling`, `general contractor`, `painting contractor`, `painter`, `remodeling contractor`, `home renovation`, `handyman`, `home repair`
- Outscraper filters: subtype CONTAINS drywall|general contractor|painter|... AND NOT hvac|asphalt|concrete|pool|...
- Output: `stage1_google.jsonl` — ~15,000-25,000 raw rows

#### Stage 2: DBPR Pull (`scraper_dbpr.py`)
- Playwright headless Chromium, 2-3 sec delay between requests
- License categories pull karenge: Gypsum Drywall Contractor, CGC, CBC, CRC, RG/RB/RR, Painting Contractor
- URL: `https://www.myfloridalicense.com/wl11.asp?mode=2&search=Name`
- Cache HTML responses
- Output: `stage2_dbpr.jsonl` — ~50,000-130,000 license rows

> **Note:** Playwright Render free tier pe chalegi but slow hogi shared CPU pe. ~1-2 hour expected for full DBPR pull. Cache aggressively.

#### Stage 3: Tier Classifier (`classifier.py` + `classification_logger.py`)
- PDF 3.3 ka exact pseudocode in `classifier.py`
- **Keywords from DB** (`keywords` table where `active=TRUE`) — loaded at job start, snapshotted to `jobs.keywords_snapshot` for reproducibility
- Order: EXCLUDE_HARD check first → TIER_1_DRYWALL → TIER_1_GC_WITH_SCOPE → TIER_2_GC_GENERIC → TIER_2_PAINTER → TIER_2_REMODELER → TIER_3_HANDYMAN → EXCLUDE_SOLO
- **For EVERY row** (including EXCLUDED), write to `classification_log` table:
  - `decision` (INCLUDED/EXCLUDED)
  - `assigned_tier`
  - `matched_keywords` — which keywords hit (with their tier source)
  - `exclusion_keywords` — which exclusion keywords hit
  - `classifier_text` — the combined text we scanned
  - `reason` — human-readable explanation
- Drop EXCLUDE rows from downstream pipeline, but **log entry persists** for audit
- Output: `stage3_classified.jsonl` (INCLUDED only) + `classification_log` table (ALL decisions)

#### Stage 4: License Match (`matcher.py`)
- Har Google row ko DBPR ke against match karte hain:
  1. Exact: normalized name + city
  2. Exact: normalized phone
  3. Fuzzy: `rapidfuzz.fuzz.token_set_ratio ≥ 88` within same ZIP
- Set `license_status` per PDF 1.3
- Output: `stage4_licensed.jsonl`

#### Stage 5: Dedupe (`dedupe.py`)
- Priority (PDF 3.4):
  1. Same normalized phone
  2. Same normalized website domain
  3. Fuzzy name (`≥ 90`) + same ZIP
  4. Same normalized address
- Output: `stage5_deduped.jsonl`

#### Stage 6: BBB Enrichment (`scraper_bbb.py`)
- Outscraper BBB actor (BBB blocks raw scrapers)
- Output: `stage6_enriched_bbb.jsonl`

#### Stage 7: Email Enrichment (`enrichment.py`)
- Order (PDF 4):
  1. Outscraper bundled emails (free, already in stage1)
  2. Hunter.io: domain → email
  3. Apollo.io: owner name + LinkedIn
  4. PDL: last-resort
- Budget cap $0.30/record
- Output: `stage7_final.jsonl`

#### Stage 8: Export (`exporter.py`)
- Insert into `contractors` table
- Write `contractors_florida_master.csv` + `.json`
- Per-city files (6 cities × 2 formats)
- Output: `/var/data/jobs/{job_id}/exports/`

**Pipeline orchestrator (`pipeline.py`) — production scraper style:**
```python
# pipeline.py — mirrors production scraper structure
import traceback
from processor import process_metro
from db import update_job, get_active_keywords, snapshot_keywords_for_job, list_cities
from schema import JobSummary

def run_pipeline(job_id: str):
    """
    Orchestrator. Reads job row, loops over metros, calls processor.process_metro
    for each. Resume-safe: skips metros already completed.
    """
    print(f"🚀 Starting pipeline for job {job_id}")
    update_job(job_id, status='running', current_stage='init')

    # Snapshot active keywords at job start (reproducibility)
    snapshot_keywords_for_job(job_id, get_active_keywords())

    try:
        metros = list_cities()  # from config/cities.yaml
        for city in metros:
            try:
                print(f"\n🏙️  Processing metro: {city.name}")
                update_job(job_id, current_stage=f'metro:{city.name}')
                process_metro(city, job_id)
                print(f"✅ Done metro: {city.name}")
            except Exception as e:
                print(f"❌ Metro {city.name} failed: {e}")
                traceback.print_exc()
                # Continue with other metros — don't crash whole pipeline

        # Final stages: global dedupe + export
        from dedupe import dedupe_all_for_job
        from exporter import export_all

        update_job(job_id, current_stage='dedupe')
        dedupe_all_for_job(job_id)

        update_job(job_id, current_stage='export')
        export_all(job_id)

        update_job(job_id, status='completed')
        print(f"🎯 Pipeline completed for job {job_id}")

    except Exception as e:
        traceback.print_exc()
        update_job(job_id, status='failed', error=str(e))
        print(f"❌ Pipeline failed: {e}")
```

**Per-metro processor (`processor.py`):**
```python
# processor.py — does ALL stages for ONE city
from scraper_google import scrape_metro
from scraper_dbpr import fetch_licenses_for_metro
from classifier import classify
from classification_logger import log_decision
from matcher import match_license
from scraper_bbb import enrich_bbb
from enrichment import enrich_email
from db import insert_contractor, get_active_keywords
from storage import write_stage_jsonl

def process_metro(city, job_id: str) -> None:
    print(f"🔍 [Metro: {city.name}] Stage 1: Google Discovery")
    seeds = scrape_metro(city.name, city.zips)  # uses DEFAULT_QUERIES + DB-derived filters
    write_stage_jsonl(job_id, 'stage1_google', city.name, seeds)

    print(f"🏛️  [Metro: {city.name}] Stage 2: DBPR Pull")
    dbpr_index = fetch_licenses_for_metro(city.name)
    write_stage_jsonl(job_id, 'stage2_dbpr', city.name, dbpr_index)

    print(f"🏷️  [Metro: {city.name}] Stage 3: Classify + Audit Log")
    keywords = get_active_keywords()
    classified = []
    for seed in seeds:
        decision = classify(seed, keywords)
        log_decision(job_id, seed, decision)  # writes to classification_log
        if decision.decision == 'INCLUDED':
            seed.tier = decision.assigned_tier
            seed.specialty_keywords = decision.matched_keywords
            classified.append(seed)

    print(f"🔗 [Metro: {city.name}] Stage 4: License Match")
    for row in classified:
        license_match = match_license(row, dbpr_index)
        row.license_status = license_match.status if license_match else 'unlicensed'
        row.license_numbers = license_match.numbers if license_match else []

    print(f"💎 [Metro: {city.name}] Stage 6: BBB Enrichment")
    for row in classified:
        bbb = enrich_bbb(row)
        row.bbb_rating = bbb.rating
        row.bbb_accredited = bbb.accredited

    print(f"📧 [Metro: {city.name}] Stage 7: Email Enrichment")
    for row in classified:
        if not row.email:
            email_result = enrich_email(row)
            row.email = email_result.email
            row.sources.extend(email_result.sources)

    # Persist contractors for this metro
    for row in classified:
        row.job_id = job_id
        insert_contractor(row)
        print(f"💾 Saved: {row.business_name} ({row.tier})")
```

Notice: same `print(f"🔍 ...")`, `try/except`, `traceback.print_exc()`, sequential-stage flow as production scraper. Dedupe + export run AFTER all metros done (need full set for cross-metro dedup).

---

### Stage 5 — React Frontend (Day 8-10 — proper multi-tab UI)

**UI Stack:** React + Vite + TypeScript + **Tailwind CSS + shadcn/ui** (free, looks production-grade, Radix primitives underneath).
**Routing:** `react-router-dom` for tab navigation.
**Data fetching:** `@tanstack/react-query` (caching, polling, optimistic updates).

**Layout:** Sidebar nav + content area.

```
┌──────────────────────────────────────────────────────────┐
│ Contractor Scraper                          🟢 API: live │
├──────────┬───────────────────────────────────────────────┤
│          │                                                │
│ 📊 Dash  │  <Active tab content>                          │
│ 🏷  Key  │                                                │
│ 👥 Res   │                                                │
│ 📋 Logs  │                                                │
│ 🗂  Hist │                                                │
│          │                                                │
└──────────┴───────────────────────────────────────────────┘
```

#### Tab 1: 📊 Dashboard
- **Big primary button** "Start Full Scrape" (shadcn `Button`, size=lg)
- Disabled when a job is `running`
- Below: **Live Progress Panel** while job runs
  - Stage cards (8 cards in vertical timeline)
  - Each card: stage name, icon (✅ done / 🔄 running spinner / ⏸ pending / ❌ failed), rows_in/rows_out counter, duration
  - Overall % progress bar
  - Elapsed time + ETA estimate
  - Cold-start indicator: "Backend waking up..." (first ~30s)
- After completion: success banner + "View Results" CTA → switches to Results tab

#### Tab 2: 🏷 Keywords (CRUD)
- **Sub-tabs per tier:** Tier 1 Drywall | Tier 1 GC | Tier 2 Painter | Tier 2 Remodeler | Tier 3 Handyman | Excludes (Hard) | Excludes (Solo)
- Each sub-tab shows a **data table** (shadcn `Table`):
  - Columns: Keyword | Active toggle | Notes | Created | Last updated | Actions (edit/delete)
  - Search bar on top
  - "+ Add Keyword" button → opens shadcn `Dialog` with form
- **Add/Edit form fields:** keyword text, active toggle, notes (optional), reason for change (optional, audit trail me jaata hai)
- **Delete confirmation:** shadcn `AlertDialog` — "Are you sure?" with reason input
- **Change log inline:** click on any keyword row → side drawer opens showing change history (`keyword_changes` table for that keyword)

#### Tab 3: 👥 Results (Contractors browser)
- **Filter bar:** Job dropdown (Latest / specific job) | City multi-select | Tier multi-select | License status filter | Search by name/phone
- **Data table** with sortable columns: Business Name | City | Tier | License Status | Phone | Email | Website | Google Rating | BBB Rating | Actions
- Click row → **detail drawer** opens:
  - All 22 fields from schema
  - **"Why included" section** — shows `classification_log` entry for this row (matched keywords highlighted)
  - Source breakdown (Google + DBPR + BBB + Apollo)
- **Top-right:** "Download CSV" + "Download JSON" buttons (filtered or all)

#### Tab 4: 📋 Logs (Classification audit)
- **Two sub-tabs:**
  - **Included** — all rows that passed classification, with their matched keywords
  - **Excluded** — all rows that were dropped (with the exclusion keyword highlighted)
- Filter: Job dropdown, Decision filter, Tier filter, Keyword search
- Data table: Business Name | Decision | Assigned Tier | Matched Keywords (pills) | Exclusion Keywords (red pills) | Reason
- Click row → drawer with full classifier text + complete log entry
- This addresses PDF Section 7 "Run log showing rows in/out per stage and reject reasons"
- **Stats summary at top:** "Job X: 4,231 INCLUDED (47% T1, 31% T2, 22% T3), 11,892 EXCLUDED (top exclusion: 'hvac' 3,201 rows)"

#### Tab 5: 🗂 History
- Past jobs list table: Job ID | Started | Duration | Status | Total Rows | Tier 1 % | Actions (View, Re-download, Delete)
- Click → loads that job's data in Results + Logs tabs

#### Polling pattern (used by Dashboard + Logs tabs during active runs):
```typescript
const { data: status } = useQuery({
  queryKey: ['job-status', jobId],
  queryFn: () => fetch(`${API_URL}/api/status/${jobId}`).then(r => r.json()),
  refetchInterval: (data) =>
    ['completed', 'failed', 'interrupted'].includes(data?.status) ? false : 2000,
});
```

**Frontend env var:**
- `VITE_API_URL=https://contractor-scraper-api.onrender.com`

**Vercel config (`vercel.json`):**
```json
{
  "buildCommand": "npm run build",
  "outputDirectory": "dist",
  "framework": "vite"
}
```

**CORS:** FastAPI me `CORSMiddleware` add karke Vercel domain whitelist.

#### shadcn/ui setup (Day 8 first thing):
```bash
cd frontend
npm create vite@latest . -- --template react-ts
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p
npx shadcn@latest init
# add commonly used components
npx shadcn@latest add button table dialog drawer alert-dialog dropdown-menu \
  input select checkbox switch tabs sidebar badge progress tooltip toast
npm install @tanstack/react-query react-router-dom lucide-react
```

---

### Stage 6 — Deployment (Day 10-11)

#### Deploy backend to Render

**Method: Render Blueprint (`render.yaml`)** — push to GitHub, auto-deploys.

```yaml
# backend/render.yaml
services:
  - type: web
    name: contractor-scraper-api
    env: python
    region: oregon
    plan: free
    buildCommand: |
      pip install -r requirements.txt
      playwright install chromium
      playwright install-deps
    startCommand: uvicorn api.main:app --host 0.0.0.0 --port $PORT
    disk:
      name: data-disk
      mountPath: /var/data
      sizeGB: 1
    envVars:
      - key: POSTGRES_DSN            # Production scraper convention (not DATABASE_URL)
        sync: false                  # Set manually in dashboard
      - key: OUTSCRAPER_API_KEY
        sync: false
      - key: HUNTER_API_KEY
        sync: false
      - key: APOLLO_API_KEY
        sync: false
      - key: PDL_API_KEY
        sync: false
      - key: FRONTEND_URL
        value: https://contractor-scraper.vercel.app
```

**`backend/requirements.txt`** (production scraper aligned + our additions):
```
# Core (from production scraper)
python-dotenv
pydantic>=2
requests
psycopg2-binary

# Web framework + async
fastapi
uvicorn[standard]
python-multipart

# Scraping
playwright                 # DBPR scraping
beautifulsoup4             # HTML parsing
outscraper                 # Outscraper Python SDK

# Matching + normalization
rapidfuzz
phonenumbers
usaddress

# Config + logging
PyYAML                     # cities.yaml parsing
loguru                     # optional, prints work too

```

🚫 **No LLM dependencies** (no `openai`, no `anthropic`, no `google-generativeai`). Project is fully rule-based + structured-API based.

**Steps:**
1. Push code to GitHub repo
2. Render dashboard → New → Blueprint → connect repo → select `backend/render.yaml`
3. Set env var values in Render dashboard (paste API keys + Neon DB URL)
4. Auto-deploys on every `git push`
5. Note the URL: `https://contractor-scraper-api.onrender.com`

#### Deploy frontend to Vercel

**Steps:**
1. Push code to same GitHub repo
2. Vercel dashboard → Import Project → select repo → Root directory: `frontend/`
3. Build settings auto-detected (Vite)
4. Environment Variables → add `VITE_API_URL=https://contractor-scraper-api.onrender.com`
5. Deploy → URL: `https://contractor-scraper.vercel.app`
6. Future pushes auto-deploy

#### Set up Neon Postgres

1. neon.tech → New Project → "contractor-scraper"
2. SQL Editor → run schema from Stage 3
3. Connection string → set as Render env `DATABASE_URL`

#### Optional: keep-alive ping

1. cron-job.org → free account → new job
2. URL: `https://contractor-scraper-api.onrender.com/health`
3. Schedule: every 10 minutes
4. Saves Render from spinning down between user sessions

---

### Stage 7 — Testing & Validation (Day 12)

**Acceptance criteria (PDF 7.2):**
- ✅ ≥ 2,000 unique businesses
- ✅ ≥ 30% Tier 1
- ✅ ≥ 90% rows with phone
- ✅ ≥ 60% rows with website OR email
- ✅ Every row has `tier` + `license_status`
- ✅ 0 hard-exclusion matches
- ✅ 0 duplicates by phone or domain
- ✅ Full run < 6 hours

**Test strategy:**
- Pehle Tampa-only local test (~300-500 rows expected)
- Then deploy + full 6-city cloud run
- Acceptance SQL queries on Neon

---

### Stage 8 — Documentation & Delivery (Day 13)

- README (< 3 pages): setup, env vars, "How to run", "How to edit keywords.yaml", troubleshooting
- `requirements.txt` pinned
- `.env.example` files for backend + frontend
- README sections:
  - "How free tier deployment works"
  - "How to resume an interrupted run"
  - "How to edit tier keywords"
  - "When to upgrade to paid tier (≥ weekly runs, or > 0.5GB data)"

---

## API Endpoints

### Jobs / pipeline
- `POST /api/jobs/start` → kicks off pipeline, returns `{job_id, status}`
- `GET  /api/jobs/{job_id}/status` → returns `{status, current_stage, stages_progress, started_at, finished_at, error}`
- `GET  /api/jobs` → list all past jobs (history tab)
- `GET  /api/jobs/{job_id}/download/{filename}` → stream CSV/JSON file
- `POST /api/jobs/{job_id}/resume` → resume interrupted job from last completed stage
- `DELETE /api/jobs/{job_id}` → delete job + its data

### Keywords CRUD (UI Tab 2)
- `GET    /api/keywords?tier=TIER_1_DRYWALL` → list keywords (filter by tier optional)
- `POST   /api/keywords` → create `{tier, keyword, notes, reason}`
- `PUT    /api/keywords/{id}` → update `{keyword?, active?, notes?, reason}`
- `DELETE /api/keywords/{id}` → soft delete with `{reason}` body
- `POST   /api/keywords/bulk` → bulk import (for re-seeding from PDF)
- `GET    /api/keywords/{id}/history` → `keyword_changes` log for this keyword

### Contractors browse (UI Tab 3)
- `GET /api/contractors?job_id=...&city=...&tier=...&license_status=...&search=...&limit=50&offset=0`
- `GET /api/contractors/{id}` → full row + classification log for this row
- `GET /api/contractors/{id}/classification` → audit trail (why included)

### Classification logs (UI Tab 4)
- `GET /api/classification-log?job_id=...&decision=INCLUDED|EXCLUDED&tier=...&search=...`
- `GET /api/classification-log/stats?job_id=...` → counts, top matched/excluded keywords, tier distribution

### Health
- `GET /api/health` → `{status: 'ok', db: 'connected', job_running: bool}` (used by cron-job.org)

---

## Critical Files to Build

### Backend (flat production-scraper structure)
| File | Purpose |
|---|---|
| `backend/agent/pipeline.py` | **Orchestrator** — loops metros, manages resume, calls processor per city |
| `backend/agent/processor.py` | **Per-metro processor** — chains all stages for ONE city (production pattern) |
| `backend/agent/scraper_google.py` | Outscraper Google Maps SDK calls → returns `List[GoogleSeed]` |
| `backend/agent/scraper_dbpr.py` | Playwright DBPR scraper → returns `List[DBPRLicense]` |
| `backend/agent/scraper_bbb.py` | Outscraper BBB actor → returns `BBBEnrichment` per row |
| `backend/agent/classifier.py` | Tier rules — loads keywords from DB, returns `ClassificationDecision` |
| `backend/agent/classification_logger.py` | Writes `classification_log` table entries for every row |
| `backend/agent/matcher.py` | Fuzzy match Google seeds ↔ DBPR licenses (rapidfuzz) |
| `backend/agent/dedupe.py` | Phone/domain/name dedup |
| `backend/agent/enrichment.py` | Email cascade: Outscraper bundled → Hunter → Apollo → PDL |
| `backend/agent/exporter.py` | CSV + JSON master + per-city files |
| `backend/agent/keywords.py` | DB keyword store + CRUD helpers (used by classifier + API) |
| `backend/agent/db.py` | **psycopg2 raw SQL** — `_get_conn()`, `CREATE TABLE IF NOT EXISTS`, inserts |
| `backend/agent/schema.py` | **All Pydantic models in one file** (production pattern) |
| `backend/agent/storage.py` | JSONL disk read/write |
| `backend/agent/seed_keywords.py` | One-time: PDF Section 1.2+3.3 → `keywords` table |
| `backend/utils/phone_normalizer.py` | E.164 + strip leading 1 |
| `backend/utils/address_normalizer.py` | usaddress wrapper |
| `backend/utils/url_normalizer.py` | Domain extract + normalize (production pattern) |
| `backend/utils/name_normalizer.py` | Lowercase + strip punctuation |
| `backend/api/main.py` | FastAPI app + CORS + lifespan |
| `backend/api/routes/jobs.py` | Jobs endpoints |
| `backend/api/routes/keywords.py` | Keywords CRUD + change log |
| `backend/api/routes/contractors.py` | Contractors browse |
| `backend/api/routes/classification.py` | Classification log endpoints |
| `backend/api/routes/health.py` | `/health` + self-ping loop |
| `backend/api/job_manager.py` | asyncio task management |
| `backend/render.yaml` | Render Blueprint for one-click deploy |
| `backend/config/cities.yaml` | 6 metros + ZIP code lists ONLY (static infrastructure) |

### Frontend
| File | Purpose |
|---|---|
| `frontend/src/App.tsx` | Sidebar layout + router |
| `frontend/src/pages/Dashboard.tsx` | Tab 1: Start button + live progress |
| `frontend/src/pages/Keywords.tsx` | Tab 2: Per-tier CRUD tables |
| `frontend/src/pages/Results.tsx` | Tab 3: Contractors browse with filters |
| `frontend/src/pages/Logs.tsx` | Tab 4: Classification audit log |
| `frontend/src/pages/History.tsx` | Tab 5: Past jobs |
| `frontend/src/components/ProgressPanel.tsx` | Live stage progress (8 stage cards) |
| `frontend/src/components/KeywordDialog.tsx` | Add/Edit keyword modal |
| `frontend/src/components/ContractorDrawer.tsx` | Side drawer with full contractor + log |
| `frontend/src/lib/api.ts` | Typed fetch wrappers |
| `frontend/src/lib/queries.ts` | react-query hooks |
| `frontend/vercel.json` | Vercel build config |

---

## Final Credentials Checklist (Stage 0 ka summary)

**Tum abhi ye karo — code shuru karne se pehle:**

### Third-party API keys (sign up + save):
- [ ] **Outscraper** signup → API token → save somewhere safe
- [ ] **Hunter.io** signup (free 25/month) → API key
- [ ] **Apollo.io** signup (free trial) → API key
- [ ] **People Data Labs** signup (optional, 100 free) → API key
- [ ] (Optional fallback) **Apify** signup → API token

### Deployment platforms (FREE):
- [ ] **GitHub** account (for source code + auto-deploy hooks)
- [ ] **Vercel** signup → connect GitHub
- [ ] **Render** signup → connect GitHub
- [ ] **Neon** signup → create project → copy DB connection string
- [ ] (Optional) **cron-job.org** signup for `/health` ping

### No keys needed:
- **Florida DBPR** — Playwright scrape (public records)
- **Google Maps direct** — Outscraper handles
- **BBB** — Outscraper actor handles

### Local dev tools:
- [ ] Python 3.11
- [ ] Node.js 20+
- [ ] Git

---

## Verification (kaise test karenge)

### Phase A — Local dev verification
1. **Secrets verify:** `backend/.env` me 4 API keys + `DATABASE_URL` (Neon)
2. **Stage 1-3 local test (Tampa-only):**
   ```bash
   cd backend
   python -m agent.run --city tampa --stages 1,2,3
   ```
3. **Local full pipeline:**
   ```bash
   python -m agent.run --full
   ```
4. **Local API + UI:**
   ```bash
   cd backend && uvicorn api.main:app --reload          # Terminal 1
   cd frontend && npm run dev                            # Terminal 2
   ```
   Browser localhost:5173 → button dabao → progress dikhna chahiye

### Phase B — Cloud deployment verification
5. **Push to GitHub → Render + Vercel auto-deploy**
6. **End-to-end test:**
   - Vercel URL kholo
   - "Start Full Scrape" button dabao
   - Progress poll hote dekho
   - ~2-6 hour me `status='completed'`
   - Download buttons enable → CSV/JSON download
7. **Neon SQL validate (acceptance criteria):**
   ```sql
   SELECT COUNT(*) FROM contractors WHERE job_id = '<latest>';                            -- ≥ 2000
   SELECT COUNT(*) FROM contractors WHERE tier LIKE 'TIER_1%' AND job_id = '<latest>';    -- ≥ 30%
   SELECT COUNT(*) FROM contractors WHERE phone IS NOT NULL AND job_id = '<latest>';      -- ≥ 90%
   SELECT phone, COUNT(*) FROM contractors WHERE job_id = '<latest>' GROUP BY phone HAVING COUNT(*) > 1;  -- 0 rows
   ```

---

## Phasing Summary

| Day | Milestone |
|---|---|
| Day 1 | All signups: Outscraper, Hunter, Apollo, PDL, GitHub, Vercel, Render, Neon |
| Day 2 | Project skeleton + Neon DB schema (6 tables) + Render env vars + seed keywords from PDF |
| Day 3-4 | Stage 1 (Outscraper Google) + Stage 3 (tier classifier + classification_log) + Tampa local test |
| Day 5-6 | Stage 2 (DBPR Playwright) + Stage 4 (license match) |
| Day 7 | Stage 5 (dedupe) + Stage 8 (export) — end-to-end without enrichment |
| Day 8 | Stage 6 (BBB) + Stage 7 (email enrichment chain) |
| Day 9 | FastAPI backend — jobs + keywords CRUD + contractors + classification log + health endpoints |
| Day 10 | Frontend skeleton — Vite + Tailwind + shadcn/ui + router + sidebar layout |
| Day 11 | Tab 1 Dashboard + Tab 2 Keywords (CRUD + change history) |
| Day 12 | Tab 3 Results + Tab 4 Logs + Tab 5 History |
| Day 13 | Deploy: GitHub push → Render auto-deploy + Vercel auto-deploy + cron-job.org keep-alive |
| Day 14 | Full 6-city cloud run + acceptance criteria validation + cost check |
| Day 15 | README + handover docs |

---

## Defaults applied from PDF "Open Questions" (Section 9)

1. **Explicit ZIP lists per metro** ✅
2. **Email enrichment v1 me include** ✅
3. **Tier 3 handymen tagged-but-included** ✅
4. **API keys YOUR ownership** ✅
5. **Re-run cadence: On-demand button only** ✅
6. **Simple web UI: YES — single-button** ✅

---

## When to upgrade beyond free tier

| Trigger | What to upgrade |
|---|---|
| > 0.5GB data accumulated | Neon Launch plan ($19/month, 10GB) OR clean old jobs |
| Pipeline unreliable due to spin-down | Render Starter plan ($7/month, no spin-down) |
| Want > 1 user / auth | Vercel + auth provider (Clerk free tier good) |
| Need real background workers | Render Background Worker ($7/month) |

For v1 single-user lead-gen tool, free tier is fine.
