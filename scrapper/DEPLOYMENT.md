# Deployment Guide

Production deployment for the Contractor Scraper Agent.

- **Frontend**: Vercel (Pro plan)
- **Backend (API + Pipeline)**: Google Cloud Run
- **Database**: Neon Postgres (already provisioned)

> Scraping pipeline runs ~3–6 hours per full run (spec acceptance criteria). Cloud Run is chosen because it supports long-running containers, streaming responses, and no 4.5 MB body cap.

---

## 1. Prerequisites

Developer machine needs:

| Tool | Why | Install |
|---|---|---|
| `gcloud` CLI | Deploy to Cloud Run | https://cloud.google.com/sdk/docs/install |
| Docker | Build container image | https://docs.docker.com/get-docker/ |
| `vercel` CLI (optional) | Frontend deploy from terminal | `npm i -g vercel` |
| Node 18+ | Frontend build | nvm/brew |

Google Cloud project access (ask client for):
- GCP project ID
- Billing enabled
- IAM role: `roles/run.admin`, `roles/iam.serviceAccountUser`, `roles/artifactregistry.writer`

```bash
gcloud auth login
gcloud config set project <PROJECT_ID>
gcloud auth configure-docker us-central1-docker.pkg.dev
```

---

## 2. Architecture at a glance

```
┌─────────────────┐   HTTPS    ┌──────────────────────────┐
│  Vercel         │ ─────────► │  Cloud Run Service       │
│  (Frontend SPA) │            │  contractor-scraper-api  │
│  Vite + React   │            │  - FastAPI / uvicorn     │
└─────────────────┘            │  - Pipeline (asyncio bg) │
                               │  - HTTP-API scrapers     │
                               └────────┬─────────────────┘
                                        │
                                        ▼
                               ┌──────────────────────────┐
                               │  Neon Postgres           │
                               │  (already set up)        │
                               └──────────────────────────┘
```

**Single Cloud Run Service** runs both API and the in-process background pipeline. Cleaner option (Cloud Run **Jobs**) noted in section 7 if/when needed.

---

## 3. Backend — Cloud Run deploy

### 3.1 Create the Dockerfile

Place this at `backend/Dockerfile`:

```dockerfile
# Slim Python base — no browser needed (DBPR uses the bulk CSV + Apify, not
# Playwright; BBB uses Apify). Small image, fast cold starts.
FROM python:3.13-slim

WORKDIR /app

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

# Cloud Run sets $PORT — uvicorn must bind to it
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port $PORT"]
```

> No Chromium/Playwright in the image — all scraping is via HTTP APIs
> (Apify actors) and the official DBPR bulk CSV download.

### 3.2 Add `.dockerignore`

Create `backend/.dockerignore`:

```
venv/
__pycache__/
*.pyc
.env
.env.local
data/
exports/
.pytest_cache/
*.log
```

### 3.3 Create Artifact Registry repo (one-time)

```bash
gcloud artifacts repositories create scraper \
    --repository-format=docker \
    --location=us-central1 \
    --description="Contractor scraper images"
```

### 3.4 Build and push image

From `backend/` directory:

```bash
cd backend

# Build via Cloud Build (no local Docker push needed)
gcloud builds submit \
    --tag us-central1-docker.pkg.dev/<PROJECT_ID>/scraper/api:latest .
```

### 3.5 Deploy to Cloud Run

```bash
gcloud run deploy contractor-scraper-api \
    --image us-central1-docker.pkg.dev/<PROJECT_ID>/scraper/api:latest \
    --region us-central1 \
    --platform managed \
    --allow-unauthenticated \
    --no-cpu-throttling \
    --min-instances=1 \
    --max-instances=3 \
    --cpu=2 \
    --memory=4Gi \
    --timeout=3600 \
    --port=8080 \
    --set-env-vars="FRONTEND_URL=https://<your-frontend>.vercel.app,DATA_DIR=/tmp/data" \
    --set-secrets="POSTGRES_DSN=postgres-dsn:latest,APIFY_API_TOKEN=apify-token:latest,APOLLO_API_KEY=apollo-key:latest"
```

### 3.6 Critical flags explained

| Flag | Why it matters |
|---|---|
| `--no-cpu-throttling` | **Required** — background pipeline runs after HTTP response returns. Default mode throttles CPU when no request is active, which would freeze the scraper mid-run. |
| `--min-instances=1` | Keep one warm instance always running. Without this, the container scales to zero after idle and kills any in-flight pipeline. |
| `--cpu=2 --memory=4Gi` | Pipeline holds the DBPR bulk index + concurrent API calls in memory. 1 vCPU/512Mi default is tight. |
| `--timeout=3600` | Per-request max (60 min). Pipeline runs in background after response, so this only matters for the longest sync endpoint (CSV export). 60 min is enough for 100k+ row exports. |
| `--allow-unauthenticated` | Frontend calls the API publicly; auth is handled by JWT in app code. |

---

## 4. Environment variables & secrets

### 4.1 Store secrets in Secret Manager (one-time)

Only **two** provider keys are needed (plus the DB):

```bash
printf '%s' '<POSTGRES_DSN>'    | gcloud secrets create postgres-dsn --data-file=-
printf '%s' '<APIFY_API_TOKEN>' | gcloud secrets create apify-token  --data-file=-
printf '%s' '<APOLLO_API_KEY>'  | gcloud secrets create apollo-key   --data-file=-
```

Give Cloud Run runtime access:

```bash
# Find the service account
PROJECT_NUMBER=$(gcloud projects describe <PROJECT_ID> --format='value(projectNumber)')
SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

# Grant secret access
for SECRET in postgres-dsn apify-token apollo-key; do
    gcloud secrets add-iam-policy-binding $SECRET \
        --member="serviceAccount:$SA" \
        --role="roles/secretmanager.secretAccessor"
done
```

### 4.2 Full env var reference

| Variable | Where | Notes |
|---|---|---|
| `POSTGRES_DSN` | Secret Manager | Neon Postgres connection string (already provisioned) |
| `APIFY_API_TOKEN` | Secret Manager | **Discovery** (Google Maps) + DBPR + BBB actors |
| `APOLLO_API_KEY` | Secret Manager | **Enrichment** — email / owner / company (paid key reveals emails) |
| `FRONTEND_URL` | Plain env | Vercel deployment URL (used in CORS) |
| `DATA_DIR` | Plain env | `/tmp/data` — Cloud Run only allows `/tmp` writes (stage JSONL only) |

> **`/tmp` is ephemeral.** Files written during a pipeline run survive only as long as the container instance. If JSONL stage files need to persist across restarts, use Google Cloud Storage (section 6). For CSV exports the answer is already covered — they stream directly in the HTTP response, no disk write needed.

---

## 5. Frontend — Vercel deploy

### 5.1 Set env vars in Vercel dashboard

Project → Settings → Environment Variables:

| Variable | Value |
|---|---|
| `VITE_API_URL` | `https://contractor-scraper-api-xxx-uc.a.run.app` (Cloud Run URL from section 3.5) |

### 5.2 Deploy

```bash
cd frontend
vercel --prod
```

Or push to the linked Git branch — auto-deploy on every commit.

Vercel config already in place (`frontend/vercel.json`):
- Build: `npm run build`
- Output: `dist`
- SPA rewrite for client-side routing

### 5.3 Update backend CORS

After first Vercel deploy, copy the production URL and redeploy backend with the new `FRONTEND_URL`:

```bash
gcloud run services update contractor-scraper-api \
    --region us-central1 \
    --update-env-vars FRONTEND_URL=https://<your-app>.vercel.app
```

---

## 6. (Optional) GCS for stage JSONL files

If the per-stage JSONL files written by `agent/storage.py` need to survive container restarts (useful for debugging mid-run, not required for normal operation), use a GCS bucket.

### 6.1 Create bucket

```bash
gcloud storage buckets create gs://<project-id>-scraper-data --location=us-central1
```

### 6.2 Grant Cloud Run service account access

```bash
gcloud storage buckets add-iam-policy-binding gs://<project-id>-scraper-data \
    --member="serviceAccount:$SA" \
    --role="roles/storage.objectAdmin"
```

### 6.3 Code change

Update `backend/agent/storage.py` to write to GCS via `google-cloud-storage` SDK. Add `google-cloud-storage>=2.10.0` to `requirements.txt`. Set `DATA_DIR=gs://<bucket>/data`.

> If you skip GCS, the CSV export feature still works fully (it streams from the DB directly to the HTTP response — no disk involved).

---

## 6.5 Weekly DBPR license refresh (required)

Stage 2 (license tagging) matches contractors against the **`dbpr_licenses`** table,
which is loaded from Florida DBPR's free, official, weekly-updated bulk CSV
(~266k construction licensees). The loader is `agent/dbpr_loader.py`:

```bash
# One-off / local
cd backend && python -m agent.dbpr_loader
```

This downloads `CONSTRUCTIONLICENSE_1.csv`, parses it, and full-replaces the table.
Businesses not found in the bulk file (e.g. Null&Void/delinquent licences, which
DBPR omits from the extract) automatically fall back to the paid Apify DBPR
verifier at scrape time — so the bulk table is the free fast-path, not the only path.

### Schedule it weekly on Cloud Run

Deploy the loader as a **Cloud Run Job** and trigger it weekly with Cloud Scheduler
(the DBPR file refreshes weekly, so daily is wasteful):

```bash
# Create the job (reuses the same image as the API)
gcloud run jobs create dbpr-refresh \
    --image us-central1-docker.pkg.dev/<PROJECT_ID>/scraper/api:latest \
    --region us-central1 \
    --command python --args "-m,agent.dbpr_loader" \
    --set-secrets="POSTGRES_DSN=postgres-dsn:latest" \
    --set-secrets="APIFY_API_TOKEN=apify-token:latest" \
    --task-timeout=600 --memory=1Gi

# Trigger every Monday 06:00 UTC
gcloud scheduler jobs create http dbpr-refresh-weekly \
    --location us-central1 \
    --schedule="0 6 * * 1" \
    --uri="https://<region>-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/<PROJECT_ID>/jobs/dbpr-refresh:run" \
    --http-method=POST \
    --oauth-service-account-email=<PROJECT_NUMBER>-compute@developer.gserviceaccount.com
```

> The loader needs `POSTGRES_DSN`; `APIFY_API_TOKEN` is only used by the runtime
> fallback at scrape time, not by the loader itself, but keeping it on the image
> env is harmless.

---

## 7. (Future) Cloud Run Jobs for the pipeline

Current setup runs the pipeline in the same container as the API via `asyncio.create_task`. Works fine, but mixes concerns. When the system scales up, split it:

- **Cloud Run Service** keeps the API endpoints (chhota, fast).
- **Cloud Run Job** runs the pipeline (24-hour max runtime, pay only when running, idle cost = 0).

Trigger pattern:

```python
# api/routes/jobs.py
@router.post("/start")
async def start_job():
    job_id = create_job_row()
    # Execute Cloud Run Job with JOB_ID env override
    run_v2_client.execute_job(
        name="projects/<PROJECT>/locations/us-central1/jobs/scraper-pipeline",
        overrides={"containerOverrides": [{"env": [{"name": "JOB_ID", "value": job_id}]}]}
    )
    return {"job_id": job_id}
```

`agent/run.py` already exists as the standalone entry point — no big refactor needed when the time comes.

Skip this for v1. Current single-service setup is fine.

---

## 8. Local development

No change from before:

```bash
# Backend
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # then fill in real values
bash start.sh

# Frontend
cd frontend
npm install
npm run dev
```

Frontend talks to `http://localhost:8000` by default. If overriding, set `VITE_API_URL` in `frontend/.env.local`.

---

## 9. Post-deploy verification

After deploying both ends:

```bash
# 1. Backend health
curl https://<cloud-run-url>/api/health
# Expected: {"status": "ok", "db": "connected"}

# 2. Auth flow
curl -X POST https://<cloud-run-url>/api/auth/login \
    -H "Content-Type: application/json" \
    -d '{"email":"...","password":"..."}'

# 3. Frontend opens and login works → results page loads → filter chips fetch facets

# 4. CSV export
# In UI: click "Download CSV (N)" — file should download in <10s for small sets,
# stream for larger sets without OOM. Verify Content-Disposition header sets filename.

# 5. Kick off a small scrape job → /api/jobs/start → poll status → confirm
# pipeline progresses through metros over ~3-6 hours. Logs visible in Cloud Run dashboard.
```

---

## 10. Costs (rough monthly estimate)

| Item | Cost |
|---|---|
| Cloud Run (min=1, 2 vCPU/4 GiB, always-on CPU) | ~$30–50/mo |
| Neon Postgres | Existing (paid by client) |
| Apify + Apollo | Pay-per-use, ~$50–100 per full pipeline run |
| Vercel Pro | Existing |
| Artifact Registry storage | <$1 |
| **Total infra** | **~$30–50/mo idle, +per-run scraper costs** |

If idle cost matters more than warm start latency, drop `--no-cpu-throttling` and `--min-instances=1`. Trade-off: background pipeline may pause when no API requests are coming in. Better long-term path is Cloud Run Jobs (section 7).

---

## 11. Already-built feature reference

These are wired and working — no extra work needed for deployment:

| Feature | Backend | Frontend |
|---|---|---|
| Filtered contractor list | `api/routes/contractors.py` (`GET /api/contractors`) | `frontend/src/pages/Results.tsx` |
| Faceted filter counts | `GET /api/contractors/facets` | `FilterChip` in Results |
| **CSV export (streaming)** | `GET /api/contractors/export` — `StreamingResponse` + server-side Postgres cursor, memory-flat for 100k+ rows | `api.exportContractors()` in `lib/api.ts`; "Download CSV (N)" button on Results page |
| Auth | `POST /api/auth/login` (JWT) | `tokenStore` in `lib/api.ts` |
| Job control | `POST /api/jobs/start`, `GET /api/jobs/{id}/status` | Dashboard page |
| Keywords admin | `/api/keywords/*` | Keywords page |
| Cities admin | `/api/cities/*` | Cities page |

CSV export specifically:
- Uses `StreamingResponse` (no in-memory buffering of the full result set)
- Server-side named cursor (`itersize=1000`) — DB streams rows in batches
- Headers: `Content-Disposition: attachment`, `Cache-Control: no-store`, `X-Accel-Buffering: no`
- Same filter/sort params as the table — exports exactly what's visible
- Frontend uses `fetch → Blob → URL.createObjectURL → hidden anchor click` (preserves auth header, unlike `window.open`)

---

## 12. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| 502 from Cloud Run after deploy | Container failed to start; check uvicorn binds to `$PORT` | Check logs: `gcloud run services logs read contractor-scraper-api --region us-central1` |
| Pipeline stops partway through | CPU throttled mid-run | Confirm `--no-cpu-throttling` and `--min-instances=1` are set |
| DBPR licenses all show "unlicensed"/"unknown" | Bulk table empty + Apify fallback failing | Run `python -m agent.dbpr_loader` (or let the first scrape auto-bootstrap it); check `APIFY_API_TOKEN` |
| CORS errors in browser | `FRONTEND_URL` env var doesn't match deployed Vercel URL | Update via `gcloud run services update ... --update-env-vars FRONTEND_URL=...` |
| CSV download fails for large sets | Cloud Run 60 min request cap hit | Either tighten filters or move export to Cloud Run Jobs (section 7) |
| Stage JSONL files missing after redeploy | Container filesystem ephemeral | Expected — use GCS (section 6) only if persistence required |
| Scrape returns only ~10 businesses per metro | The temporary discovery cap is active | Expected during testing — see §13 to lift it |

---

## 13. ⚠️ Discovery (Apify Google Maps) — TEMPORARY 10-RESULT CAP (remove before client handoff)

Stage 1 (Google discovery) uses the **Apify Google Maps actor**
`compass/crawler-google-places` — the sole discovery source (no separate
Outscraper key). Code: `backend/agent/scraper_google.py` (`scrape_metro` →
`_scrape_apify_maps` → `_apify_place_to_seed`). Needs `APIFY_API_TOKEN`.

**A hardcoded safety cap is in place** so early/test runs can't scrape thousands
of rows or run up Apify cost before the client is ready:

```python
# backend/agent/scraper_google.py
DISCOVERY_RESULT_CAP = 10   # ← at most 10 businesses PER METRO
```

- With the cap, a full 6-metro run yields at most ~60 businesses total, and the
  actor runs only the **first** search query (`queries[:1]`) per metro.
- This intentionally does NOT meet the spec's "≥ 2,000 businesses" acceptance
  criterion — it is a deliberate throttle for the pre-handoff phase.

### 🔧 To go full-scale (when handing the client the real dataset)

1. Edit `backend/agent/scraper_google.py`: set `DISCOVERY_RESULT_CAP = None`.
   The actor then runs **all** `DEFAULT_QUERIES` per metro with
   `maxCrawledPlacesPerSearch=120`.
2. Confirm `APIFY_API_TOKEN` is funded (Apify Google Maps ≈ $50–75 for a full run).
3. Redeploy. The next scrape discovers the full 3,000–5,000-business universe.

> **Do not ship the cap to the client.** It silently limits output to 10/metro.
> This is the single most important pre-handoff toggle.

### Field mapping (`_apify_place_to_seed`, already implemented)
Maps compass actor output: `title→business_name`, `address→address`,
`postalCode→zip_code`, `phoneUnformatted→`E.164, `website→website`,
`emails→email`, `categoryName/categories→google_categories`,
`totalScore→google_rating`, `reviewsCount→google_review_count`,
`facebooks/instagrams/linkedIns→social_profiles`. `scrapeContacts: true` pulls
emails + socials in the same pass. Subtype include/exclude is enforced by the
Stage-3 classifier, not at scrape time.

> ⚠️ The live Apify Maps path is **wired and unit-mapped but not yet live-tested**
> — the dev's Apify free credit was exhausted during build. Run one live scrape
> on the funded production token to confirm before relying on it.
