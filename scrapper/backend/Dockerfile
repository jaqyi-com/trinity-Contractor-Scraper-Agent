# Slim Python base — no browser needed (DBPR uses the bulk CSV + Apify, not
# Playwright; BBB uses Apify). Small image, fast cold starts.
FROM python:3.13-slim

# Real-time logs in Cloud Run (pipeline uses print() heavily) + no .pyc clutter.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Python deps (cached layer — only re-runs when requirements.txt changes).
# psycopg2-binary + bcrypt ship prebuilt wheels, so no gcc/libpq-dev needed.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

# Cloud Run injects $PORT (defaults to 8080) — uvicorn must bind to it.
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port $PORT"]
