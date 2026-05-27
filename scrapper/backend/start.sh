#!/bin/bash
# Local dev launch script
# Usage: bash start.sh

set -e

# Activate venv if exists
if [ -d "venv" ]; then
  source venv/bin/activate
fi

# Unbuffered stdout so background-pipeline print() logs appear live (not buffered)
export PYTHONUNBUFFERED=1

# Start FastAPI with hot reload
exec uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
