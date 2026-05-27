# Deployment Guide

Production deployment for the Contractor Scraper Agent.

- **Frontend**: Vercel (Pro plan)
- **Backend (API + Pipeline)**: Google Cloud Run
- **Database**: Neon Postgres (already provisioned)

> Scraping pipeline runs ~3–6 hours per full run (spec acceptance criteria). Cloud Run is chosen because it supports long-running containers, Playwright/Chromium, streaming responses, and no 4.5 MB body cap.

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
                               │  - Playwright (Chromium) │
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
# Playwright official image — already has Chromium + system deps
FROM mcr.microsoft.com/playwright/python:v1.41.0-jammy

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

> Using the official Playwright base image saves ~10 min of build time vs `playwright install chromium` from scratch.

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
    --set-env-vars="FRONTEND_URL=https://<your-frontend>.vercel.app,DATA_DIR=/tmp/data,EXPORT_DIR=/tmp/exports" \
    --set-secrets="POSTGRES_DSN=postgres-dsn:latest,OUTSCRAPER_API_KEY=outscraper-key:latest,APOLLO_API_KEY=apollo-key:latest,HUNTER_API_KEY=hunter-key:latest,APIFY_API_TOKEN=apify-token:latest"
```

### 3.6 Critical flags explained

| Flag | Why it matters |
|---|---|
| `--no-cpu-throttling` | **Required** — background pipeline runs after HTTP response returns. Default mode throttles CPU when no request is active, which would freeze the scraper mid-run. |
| `--min-instances=1` | Keep one warm instance always running. Without this, the container scales to zero after idle and kills any in-flight pipeline. |
| `--cpu=2 --memory=4Gi` | Playwright + scraping needs headroom. 1 vCPU/512Mi default will OOM. |
| `--timeout=3600` | Per-request max (60 min). Pipeline runs in background after response, so this only matters for the longest sync endpoint (CSV export). 60 min is enough for 100k+ row exports. |
| `--allow-unauthenticated` | Frontend calls the API publicly; auth is handled by JWT in app code. |

---

## 4. Environment variables & secrets

### 4.1 Store secrets in Secret Manager (one-time)

```bash
echo -n "postgresql://neondb_owner:..." | gcloud secrets create postgres-dsn --data-file=-
echo -n "<outscraper-key>" | gcloud secrets create outscraper-key --data-file=-
echo -n "<apollo-key>" | gcloud secrets create apollo-key --data-file=-
echo -n "<hunter-key>" | gcloud secrets create hunter-key --data-file=-
echo -n "apify_api_5PQ5vUb2vPNxeagWOmHxROp2nHUG9V0nK0sj" | gcloud secrets create apify-token --data-file=-
```

Give Cloud Run runtime access:

```bash
# Find the service account
PROJECT_NUMBER=$(gcloud projects describe <PROJECT_ID> --format='value(projectNumber)')
SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

# Grant secret access
for SECRET in postgres-dsn outscraper-key apollo-key hunter-key apify-token; do
    gcloud secrets add-iam-policy-binding $SECRET \
        --member="serviceAccount:$SA" \
        --role="roles/secretmanager.secretAccessor"
done
```

### 4.2 Full env var reference

| Variable | Where | Notes |
|---|---|---|
| `POSTGRES_DSN` | Secret Manager | Neon Postgres connection string (already provisioned) |
| `OUTSCRAPER_API_KEY` | Secret Manager | Google Maps scraping |
| `APOLLO_API_KEY` | Secret Manager | Email enrichment |
| `HUNTER_API_KEY` | Secret Manager | Email enrichment fallback |
| `PDL_API_KEY` | Secret Manager (optional) | People Data Labs — last-resort enrichment |
| `APIFY_API_TOKEN` | Secret Manager | BBB scraper actor |
| `FRONTEND_URL` | Plain env | Vercel deployment URL (used in CORS) |
| `DATA_DIR` | Plain env | `/tmp/data` — Cloud Run only allows `/tmp` writes |
| `EXPORT_DIR` | Plain env | `/tmp/exports` — see below |

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

Update `backend/agent/storage.py` to write to GCS via `google-cloud-storage` SDK. Add `google-cloud-storage>=2.10.0` to `requirements.txt`. Set `EXPORT_DIR=gs://<bucket>/exports`.

> If you skip GCS, the CSV export feature still works fully (it streams from the DB directly to the HTTP response — no disk involved).

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
playwright install chromium
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
| Outscraper / Apollo / Hunter / Apify | Pay-per-use, ~$50–100 per full pipeline run |
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
| Playwright errors "browser not found" | Wrong base image | Use `mcr.microsoft.com/playwright/python:vX.Y.Z-jammy` |
| CORS errors in browser | `FRONTEND_URL` env var doesn't match deployed Vercel URL | Update via `gcloud run services update ... --update-env-vars FRONTEND_URL=...` |
| CSV download fails for large sets | Cloud Run 60 min request cap hit | Either tighten filters or move export to Cloud Run Jobs (section 7) |
| Stage JSONL files missing after redeploy | Container filesystem ephemeral | Expected — use GCS (section 6) only if persistence required |
