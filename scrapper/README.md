# Contractor Scraper Agent — Florida Lead Gen

Production-style scraper that pulls drywall / GC / painter / handyman businesses from 6 Florida metros, tags by tier + license status, and exports CSV/JSON for outbound sales.

Spec: `Contractor_Scraper_Agent_Spec_v2 (1).pdf`
Plan: `PLAN.md`
Credentials: `REQUIREMENTS.md`

## Stack

- **Backend:** Python 3.11 + FastAPI + psycopg2 (raw SQL) + Pydantic
- **Frontend:** React + Vite + TypeScript + Tailwind + shadcn-style components
- **DB:** PostgreSQL (Neon free tier in dev)
- **Deploy (dev):** Render (backend) + Vercel (frontend) + Neon (db)

## Project Layout

```
.
├── backend/                  # FastAPI + scraping pipeline
│   ├── agent/                # Pipeline + per-source scrapers (flat structure)
│   ├── api/                  # FastAPI app + routes
│   ├── utils/                # Pure helpers (normalizers)
│   ├── config/cities.yaml    # 6 metros + ZIPs
│   ├── requirements.txt
│   ├── .env (gitignored)     # API keys
│   └── render.yaml           # Render Blueprint
├── frontend/                 # React + Vite UI
│   ├── src/
│   │   ├── pages/            # 5 tabs: Dashboard / Keywords / Results / Logs / History
│   │   ├── components/
│   │   └── lib/api.ts        # Typed API client
│   └── package.json
├── PLAN.md
├── REQUIREMENTS.md
└── Scraping_code/            # Reference: production scraper (gitignored)
```

## Quick Start (local dev)

### 1. Fill in API keys

```bash
cp backend/.env.example backend/.env
# Edit backend/.env — fill in:
#   POSTGRES_DSN, APIFY_API_TOKEN, APOLLO_API_KEY
```

Sign up for each service per `REQUIREMENTS.md`.

### 2. Backend

```bash
cd backend
source venv/bin/activate                  # venv already created
python -m agent.run --init-db             # creates Postgres tables
python -m agent.run --seed                # loads PDF default keywords
uvicorn api.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

### 3. Frontend

```bash
cd frontend
npm run dev
```

Open http://localhost:5173

### 4. Run full pipeline

Option A — via UI: click "Start Full Scrape" on Dashboard tab.
Option B — via CLI: `cd backend && python -m agent.run --full`

## Deploy (free tier)

See `PLAN.md` → Stage 6 — Deployment. tl;dr:

1. Push to GitHub
2. Render → New → Blueprint → `backend/render.yaml`
3. Vercel → Import → `frontend/` as root
4. Neon → New project → copy `POSTGRES_DSN` into Render env vars

## Architecture Notes

- **Pipeline + Processor split** (production scraper pattern): `pipeline.py` orchestrates, `processor.py` does per-metro work.
- **psycopg2 + raw SQL** — `db.py` self-bootstraps tables via `CREATE TABLE IF NOT EXISTS`. No ORM.
- **Single `schema.py`** with all Pydantic models.
- **Audit logging** — every classification decision (INCLUDED + EXCLUDED) written to `classification_log`.
- **Keywords in DB** — user-managed CRUD via UI Tab 2, with full change history.
- **No timeout** — `/api/jobs/start` returns in <500ms with `job_id`; pipeline runs as background asyncio task; frontend polls `/status` every 2s.

## Status

- [x] Folder skeleton
- [x] Backend modules
- [x] FastAPI routes
- [x] Frontend with all tabs
- [x] Apify Google Maps discovery (`scraper_google.py`)
- [x] DBPR via bulk CSV + Apify fallback (`scraper_dbpr.py`, `dbpr_loader.py`)
- [x] BBB Apify actor (`scraper_bbb.py`)
- [x] Apollo email/owner/company enrichment (`enrichment.py`)
- [x] Keywords CRUD, Results browser, Logs
