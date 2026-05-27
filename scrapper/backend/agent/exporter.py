# exporter.py
# Stage 8: write master CSV + JSON + per-city files.

import csv
import json
import os
from typing import List
from pathlib import Path
from dotenv import load_dotenv

from agent.schema import ContractorRow

load_dotenv()

EXPORT_DIR = os.getenv("EXPORT_DIR", "./exports")


CSV_COLUMNS = [
    "business_name", "city", "zip_code", "address",
    "tier", "specialty_keywords", "google_categories", "services_listed",
    "phone", "email", "website", "owner_name",
    "license_status", "license_numbers", "license_categories",
    "google_rating", "google_review_count",
    "bbb_rating", "bbb_accredited", "years_in_business",
    "social_profiles", "sources", "place_ids", "scraped_at",
]


def _row_to_csv_dict(row: ContractorRow) -> dict:
    d = row.model_dump(mode="json")
    # JSON-encode list/dict fields for CSV
    for col in ["specialty_keywords", "google_categories", "services_listed",
                "license_numbers", "license_categories", "social_profiles",
                "sources", "place_ids"]:
        d[col] = json.dumps(d.get(col) or ([] if col != "social_profiles" else {}))
    return {k: d.get(k) for k in CSV_COLUMNS}


def export_master_csv(rows: List[ContractorRow], job_id: str) -> str:
    out_dir = Path(EXPORT_DIR) / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "contractors_florida_master.csv"

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(_row_to_csv_dict(row))

    print(f"💾 Wrote {path}")
    return str(path)


def export_master_json(rows: List[ContractorRow], job_id: str) -> str:
    out_dir = Path(EXPORT_DIR) / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "contractors_florida_master.json"

    with open(path, "w", encoding="utf-8") as f:
        json.dump([r.model_dump(mode="json") for r in rows], f, indent=2, default=str)

    print(f"💾 Wrote {path}")
    return str(path)


def export_per_city(rows: List[ContractorRow], job_id: str) -> List[str]:
    paths: List[str] = []
    by_city: dict = {}
    for r in rows:
        by_city.setdefault((r.city or "unknown").lower().replace(" ", "_"), []).append(r)

    out_dir = Path(EXPORT_DIR) / job_id
    out_dir.mkdir(parents=True, exist_ok=True)

    for city, city_rows in by_city.items():
        csv_path = out_dir / f"contractors_{city}.csv"
        json_path = out_dir / f"contractors_{city}.json"

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            for row in city_rows:
                writer.writerow(_row_to_csv_dict(row))

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump([r.model_dump(mode="json") for r in city_rows], f, indent=2, default=str)

        paths.extend([str(csv_path), str(json_path)])
        print(f"💾 Wrote {csv_path} + {json_path} ({len(city_rows)} rows)")

    return paths


def export_all(job_id: str) -> dict:
    """TODO: load contractors for job_id from DB, run all exports."""
    print(f"📦 [Export] job_id={job_id}")
    return {"master_csv": "", "master_json": "", "per_city": []}
