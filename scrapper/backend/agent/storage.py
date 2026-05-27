# storage.py
# JSONL read/write on local disk (Render Persistent Disk in production).

import os
import json
from pathlib import Path
from typing import Iterable, Any
from dotenv import load_dotenv

load_dotenv()

DATA_DIR = os.getenv("DATA_DIR", "./data")


def _stage_path(job_id: str, stage_name: str, suffix: str = "") -> Path:
    base = Path(DATA_DIR) / "jobs" / job_id
    base.mkdir(parents=True, exist_ok=True)
    fname = f"{stage_name}{('_' + suffix) if suffix else ''}.jsonl"
    return base / fname


def write_stage_jsonl(job_id: str, stage_name: str, suffix: str, rows: Iterable[Any]) -> Path:
    path = _stage_path(job_id, stage_name, suffix)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            if hasattr(r, "model_dump_json"):
                f.write(r.model_dump_json() + "\n")
            else:
                f.write(json.dumps(r, default=str) + "\n")
    return path


def read_stage_jsonl(job_id: str, stage_name: str, suffix: str = ""):
    path = _stage_path(job_id, stage_name, suffix)
    if not path.exists():
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)
