# sheets_schema.py
# Tab → header mapping + per-column type coercion for the Sheets storage layer.
#
# These headers MUST match the Postgres column order they replaced (see the old
# agent/db.py::init_schema CREATE TABLEs) so the PG→Sheets migration CLI can copy
# rows column-for-column without remapping.
#
# Type metadata drives the encode/decode helpers below: JSONB columns serialise
# to JSON strings, TIMESTAMPTZ to ISO 8601, BOOL to "true"/"false", everything
# else to plain text. Reads reverse the transform so calling code never sees
# raw cell strings.

import json
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Set


# ──────────────────────────────────────────────────────────────
# Tab schemas
# Keys per tab:
#   headers         — column order (row 1 of the tab)
#   id_field        — column that uniquely identifies a row; used for
#                     in-memory id→row_index lookup. None = no id.
#   id_kind         — 'int' (auto-increment from counter) | 'uuid' | 'composite'
#   json_fields     — encode/decode as JSON
#   datetime_fields — encode/decode as ISO 8601
#   bool_fields     — encode/decode as 'true'/'false'
#   int_fields / float_fields — coerce on read
# ──────────────────────────────────────────────────────────────
SCHEMA: Dict[str, Dict[str, Any]] = {
    "jobs": {
        "headers": [
            "job_id", "status", "current_stage", "stages_progress",
            "started_at", "finished_at", "error", "keywords_snapshot",
            "resume_from",
            # DEPRECATED — dynamic-sheets feature removed. Kept only so existing
            # sheets' column positions stay aligned (never written anymore).
            "result_sheet_id", "result_sheet_url", "result_sheet_name",
            # Batch name for this run ("Batch 1", …) — the UI filters contractors by it.
            "name",
        ],
        "id_field": "job_id",
        "id_kind": "uuid",
        "json_fields": {"stages_progress", "keywords_snapshot"},
        "datetime_fields": {"started_at", "finished_at"},
        "bool_fields": set(),
        "int_fields": set(),
        "float_fields": set(),
    },
    # Stop signal lives here, NOT in `jobs`, so the API service (writer of the
    # stop flag) and the pipeline worker (writer of progress) never clobber each
    # other's fields when they run as separate processes (Cloud Run Job mode).
    "job_control": {
        "headers": ["job_id", "stop_requested", "updated_at"],
        "id_field": "job_id",
        "id_kind": "composite",
        "json_fields": set(),
        "datetime_fields": {"updated_at"},
        "bool_fields": {"stop_requested"},
        "int_fields": set(),
        "float_fields": set(),
    },
    "contractors": {
        "headers": [
            "id", "business_name", "city", "zip_code", "address", "tier",
            "specialty_keywords", "google_categories", "services_listed",
            "phone", "email", "website", "owner_name",
            "license_status", "license_numbers", "license_categories",
            "google_rating", "google_review_count",
            "bbb_rating", "bbb_accredited", "years_in_business",
            "social_profiles", "sources", "place_ids", "dedupe_key",
            "scraped_at", "job_id",
        ],
        "id_field": "id",
        "id_kind": "int",
        "json_fields": {
            "specialty_keywords", "google_categories", "services_listed",
            "license_numbers", "license_categories",
            "social_profiles", "sources", "place_ids",
        },
        "datetime_fields": {"scraped_at"},
        "bool_fields": {"bbb_accredited"},
        "int_fields": {"id", "google_review_count", "years_in_business"},
        "float_fields": {"google_rating"},
    },
    "stage_outputs": {
        "headers": ["id", "job_id", "stage_name", "row_index", "data", "created_at"],
        "id_field": "id",
        "id_kind": "int",
        "json_fields": {"data"},
        "datetime_fields": {"created_at"},
        "bool_fields": set(),
        "int_fields": {"id", "row_index"},
        "float_fields": set(),
    },
    "keywords": {
        "headers": [
            "id", "tier", "keyword", "active", "notes",
            "created_at", "updated_at", "created_by",
        ],
        "id_field": "id",
        "id_kind": "int",
        "json_fields": set(),
        "datetime_fields": {"created_at", "updated_at"},
        "bool_fields": {"active"},
        "int_fields": {"id"},
        "float_fields": set(),
    },
    "keyword_changes": {
        "headers": [
            "id", "keyword_id", "action", "tier", "keyword",
            "before_data", "after_data", "changed_by", "changed_at", "reason",
        ],
        "id_field": "id",
        "id_kind": "int",
        "json_fields": {"before_data", "after_data"},
        "datetime_fields": {"changed_at"},
        "bool_fields": set(),
        "int_fields": {"id", "keyword_id"},
        "float_fields": set(),
    },
    "classification_log": {
        "headers": [
            "id", "job_id", "contractor_id", "business_name", "place_id",
            "decision", "assigned_tier", "matched_keywords", "exclusion_keywords",
            "classifier_text", "reason", "created_at",
        ],
        "id_field": "id",
        "id_kind": "int",
        "json_fields": {"matched_keywords", "exclusion_keywords"},
        "datetime_fields": {"created_at"},
        "bool_fields": set(),
        "int_fields": {"id", "contractor_id"},
        "float_fields": set(),
    },
    "users": {
        "headers": ["id", "email", "name", "password_hash", "created_at"],
        "id_field": "id",
        "id_kind": "int",
        "json_fields": set(),
        "datetime_fields": {"created_at"},
        "bool_fields": set(),
        "int_fields": {"id"},
        "float_fields": set(),
    },
    "cities": {
        "headers": ["id", "name", "state", "created_at", "updated_at"],
        "id_field": "id",
        "id_kind": "int",
        "json_fields": set(),
        "datetime_fields": {"created_at", "updated_at"},
        "bool_fields": set(),
        "int_fields": {"id"},
        "float_fields": set(),
    },
    "city_zips": {
        "headers": ["id", "city_id", "zip_code", "created_at"],
        "id_field": "id",
        "id_kind": "int",
        "json_fields": set(),
        "datetime_fields": {"created_at"},
        "bool_fields": set(),
        "int_fields": {"id", "city_id"},
        "float_fields": set(),
    },
    "app_settings": {
        "headers": ["key", "value", "updated_at"],
        "id_field": "key",
        "id_kind": "composite",
        "json_fields": set(),
        "datetime_fields": {"updated_at"},
        "bool_fields": set(),
        "int_fields": set(),
        "float_fields": set(),
    },
}

TAB_NAMES: List[str] = list(SCHEMA.keys())

# Ephemeral tabs are created at bootstrap but NOT loaded into the in-RAM mirror
# (_load_mirror skips them). They hold large, short-lived data — e.g. pipeline
# stage checkpoints for stop/resume — that would otherwise blow the 512MB mirror.
# Read/written via the direct SheetsDB.ephemeral_* helpers, never the mirror.
EPHEMERAL_TABS: Set[str] = {"stage_outputs"}


# ──────────────────────────────────────────────────────────────
# Encode (Python value → cell string) / Decode (cell string → Python)
# Sheets stores everything as strings (or floats). We round-trip through
# JSON for arrays/objects and ISO 8601 for timestamps so reads come back
# in the same shape the old psycopg2 code returned.
# ──────────────────────────────────────────────────────────────
def _encode_cell(field: str, value: Any, spec: Dict[str, Any]) -> str:
    if value is None:
        return ""
    if field in spec["json_fields"]:
        if isinstance(value, str):
            # Already a JSON string — trust it.
            return value
        try:
            return json.dumps(value, default=str)
        except (TypeError, ValueError):
            return json.dumps(str(value))
    if field in spec["datetime_fields"]:
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return str(value)
    if field in spec["bool_fields"]:
        return "true" if bool(value) else "false"
    return str(value)


def _decode_cell(field: str, value: Any, spec: Dict[str, Any]) -> Any:
    # gspread returns "" for empty cells; sometimes numeric values come back as int/float already.
    if value == "" or value is None:
        return None
    if field in spec["json_fields"]:
        if isinstance(value, (list, dict)):
            return value
        try:
            return json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    if field in spec["datetime_fields"]:
        s = str(value)
        try:
            return datetime.fromisoformat(s)
        except (TypeError, ValueError):
            return s   # leave as raw string if non-ISO; caller can handle
    if field in spec["bool_fields"]:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "1", "yes", "t")
    if field in spec["int_fields"]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    if field in spec["float_fields"]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return value


def encode_row(tab: str, record: Dict[str, Any]) -> List[str]:
    """Serialise a record into a row matching SCHEMA[tab]['headers'] order."""
    spec = SCHEMA[tab]
    return [_encode_cell(h, record.get(h), spec) for h in spec["headers"]]


def decode_row(tab: str, row: List[Any]) -> Dict[str, Any]:
    """Inverse of encode_row — returns a dict matching the old psycopg2 row shape."""
    spec = SCHEMA[tab]
    out: Dict[str, Any] = {}
    headers = spec["headers"]
    for i, h in enumerate(headers):
        cell = row[i] if i < len(row) else None
        out[h] = _decode_cell(h, cell, spec)
    return out


def headers_for(tab: str) -> List[str]:
    return SCHEMA[tab]["headers"]
