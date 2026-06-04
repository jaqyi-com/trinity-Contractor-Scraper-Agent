# Contractor Scraper Agent — Florida Lead Gen

Scrapes drywall / general-contractor / painter / handyman businesses across 6 Florida
metros, tags each by **tier** and **license status**, dedupes, and serves the results
through a web UI + downloadable spreadsheets for outbound sales.

Spec: `Contractor_Scraper_Agent_Spec_v2 (1).pdf`

---

## Stack

- **Backend:** Python 3.13 · FastAPI · Pydantic
- **Datastore:** **Google Sheets** (a spreadsheet with one tab per "table") — there is no SQL DB
- **Frontend:** React · Vite · TypeScript · Tailwind
- **Hosting:** Google **Cloud Run** (API service) + Cloud Run **Jobs** (the long pipeline) + **Vercel** (frontend)
- **External APIs:** Apify (discovery + BBB + DBPR fallback) · Apollo (email/owner enrichment)

---

## How it works

### Pipeline (6 phases, runs ~hours)

1. **Discovery** — Apify Google Maps actor scrapes each metro (paid per place).
2. **Dedupe seeds** — collapse duplicates *before* paid enrichment.
3. **Classify** — keyword classifier tags each business Tier 1/2/3 or excludes it (free).
4. **Cap** — keep the strongest N leads (`max_final_records`, default 5000).
5. **DBPR + Enrich + Save** — license match + BBB/Apollo enrichment, then **UPSERT** into the `contractors` master tab.
6. **Final dedupe** — post-insert sweep.

### DBPR licenses (streamed, low-memory)

Florida's official ~266k-row construction-license CSV is **streamed and match-filtered**
on demand (`agent/dbpr_loader.py`) — only the rows matching discovered names are kept in
memory (~10MB peak). It is never bulk-loaded, so it can't OOM the 512MB container. Data is
fresh every run (the CSV is fetched live in phase 5). Names absent from the bulk file fall
back to the paid Apify DBPR verifier.

### Stop / Resume / Start

The pipeline checkpoints its working set after every phase to a non-mirrored
`stage_outputs` tab, and records the next phase in the `jobs` tab. The **Stop** button
(Dashboard) sets a flag in a `job_control` tab; the pipeline pauses at the next phase
boundary (the expensive discovery never re-runs). **Resume** continues from the checkpoint;
**Cancel** discards a paused run. Progress shows as a live animated stepper in the UI.

### Per-run dynamic result sheets

Each run also writes its results to its **own dated Google Sheet** in a shared Drive folder,
one row per business tagged `change_status` = **new / updated / unchanged** (vs the master
tab). The cumulative `contractors` master tab is unchanged. In the UI's **Results** page a
selector picks the result set: default = latest run's sheet, or "Master — all runs", or any
past run; each run links out to "Open in Google Sheets".

---

## API keys needed

| Service | Env var | Used for | Notes |
|---|---|---|---|
| **Apify** | `APIFY_API_TOKEN` | Google Maps discovery + BBB + DBPR fallback | ~$50–75 / full 6-metro run |
| **Apollo.io** | `APOLLO_API_KEY` | email / owner / company enrichment | **must be a PAID key** — free tier masks emails |

No keys needed for Florida DBPR (free official CSV) or Google Maps/BBB (accessed via Apify).

---

## Environment variables

Copy `backend/.env.example` → `backend/.env` (local) or set them on Cloud Run. Essentials:

- **Sheets:** `GOOGLE_SHEETS_ID`, `GOOGLE_CLIENT_EMAIL`, `GOOGLE_PRIVATE_KEY`
- **Dynamic sheets:** `DRIVE_RESULTS_FOLDER_ID`
- **Scraping:** `APIFY_API_TOKEN`, `APOLLO_API_KEY`
- **Auth:** `JWT_SECRET`

Everything else auto-detects (runner mode, project/region) or has a default
(`PIPELINE_RUNNER`, `GCP_PROJECT`, `GCP_REGION`, `CLOUD_RUN_JOB`, `METRO_WORKERS`,
`ENRICH_WORKERS`, `SHEETS_FLUSH_*`, `JOB_TASK_TIMEOUT`, `FRONTEND_URL`, …).

---

## Local development

```bash
# Backend
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in the values
bash start.sh                 # uvicorn on :8000 (pipeline runs in a background thread)

# Frontend
cd frontend
npm install
npm run dev                   # Vite on :5173
```

Locally the pipeline runs in-process (thread mode) — no GCP needed. You can also run one
pipeline execution exactly like the Cloud Run Job does:

```bash
JOB_ID=<existing-job-id> RESUME=false python -m agent.run_job
```

---

## Deployment (Google Cloud Run)

**Two pieces share one container image:**
- **Service** `trinity-contractor-scraper-agent` (region `europe-west1`) — the FastAPI API + UI backend.
- **Job** `contractor-pipeline-job` — runs the pipeline with full CPU for hours (logs stream
  reliably to Cloud Logging). Triggered on-demand by the service when you click Start/Resume.

### Mostly automatic

- **Runner mode auto-detects** — on Cloud Run it uses Job mode; locally, thread mode. No `PIPELINE_RUNNER` needed.
- **The Job auto-creates/updates itself on every deploy** — when the service boots it reads
  its own container config and mirrors it into the Job (`api/cloud_run_trigger.ensure_pipeline_job`).
  Just push code as usual.

### The one-time manual step (Console clicks, no terminal)

The app can't self-grant IAM. Give the service's **service account** (the Compute Engine
default SA, `<project-number>-compute@developer.gserviceaccount.com`) two roles, once, in
**IAM & Admin → IAM**:
- **Cloud Run Admin** (`roles/run.admin`)
- **Service Account User** (`roles/iam.serviceAccountUser`)

> Sheets/Apify auth uses the env credentials (not the runtime SA), so the Job needs no extra data permissions.

### Dynamic result sheets — Drive folder setup

1. In Google Drive, create a folder (e.g. "Contractor Scraper Runs").
2. Share it with `GOOGLE_CLIENT_EMAIL` as **Editor**.
3. Copy the folder ID from its URL and set `DRIVE_RESULTS_FOLDER_ID` on the service.

(Native Google Sheets don't count against storage quota, so the service account can create them freely.)

### Frontend (Vercel)

Set `VITE_API_URL` to the Cloud Run service URL, then `vercel --prod` (or push to the linked branch).
Keep the service's `FRONTEND_URL` pointed at the Vercel URL for CORS.

### Watching pipeline logs

Cloud Run → **Jobs** → `contractor-pipeline-job` → **Executions** → pick one → **LOGS**
(all `print()` output, live; `PYTHONUNBUFFERED=1` is set).

---

## ⚠️ Important toggle before full-scale handoff

`backend/agent/scraper_google.py` has a **temporary discovery cap**:

```python
DISCOVERY_RESULT_CAP = 10   # at most 10 businesses PER METRO (test throttle)
```

This keeps test runs cheap (~60 businesses total) and does **not** meet the spec's
"≥ 2,000 businesses". To go full-scale set `DISCOVERY_RESULT_CAP = None`, ensure
`APIFY_API_TOKEN` is funded, and redeploy.

---

## Project layout

```
scrapper/
├── backend/
│   ├── agent/                 # pipeline + scrapers (flat)
│   │   ├── pipeline.py        # phased orchestrator + stop/resume
│   │   ├── processor.py       # per-phase workers (discover/classify/enrich)
│   │   ├── scraper_google.py  # Apify Google Maps discovery  (⚠ DISCOVERY_RESULT_CAP)
│   │   ├── scraper_dbpr.py / dbpr_loader.py   # DBPR license match (streamed CSV)
│   │   ├── scraper_bbb.py / enrichment.py     # BBB + Apollo
│   │   ├── classifier.py / keywords.py        # tier classifier
│   │   ├── dedupe.py / matcher.py
│   │   ├── checkpoint.py      # stop/resume checkpoints (stage_outputs tab)
│   │   ├── dynamic_sheets.py  # per-run result spreadsheets
│   │   ├── db.py / sheets_client.py / sheets_schema.py   # Google Sheets storage layer
│   │   └── run_job.py         # Cloud Run Job entrypoint (python -m agent.run_job)
│   ├── api/
│   │   ├── main.py            # FastAPI app + lifespan (auto-ensures the Job)
│   │   ├── job_manager.py / cloud_run_trigger.py   # thread vs Cloud Run Job
│   │   └── routes/            # jobs, contractors, result_sheets, keywords, cities, classification, auth, health
│   ├── config/cities.yaml     # 6 metros + ZIPs
│   ├── requirements.txt · Dockerfile · start.sh · .env.example
└── frontend/
    └── src/pages/             # Dashboard · Keywords · Results · Cities · Logs · History
```
