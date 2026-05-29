# dbpr_loader.py
# In-memory DBPR licensee store — replaces the old dbpr_licenses Postgres table.
#
# Flow:
#   1. Pipeline start (or first query) calls refresh_dbpr_licenses().
#   2. We download the official Florida CSV (~266k rows) once per process,
#      parse it into a pandas DataFrame, and build a dict index keyed by
#      normalized_name → list[record].
#   3. query_by_normalized_names() is now a microsecond dict lookup; no SQL,
#      no Sheets round-trip, no rate limit.
#
# Sheets is intentionally NOT used for DBPR: 266k * 15 columns = ~4M cells —
# under the 10M hard cap but borderline, and every refresh would consume a huge
# write quota. Holding it in process memory is faster AND cheaper.

import csv
import io
import threading
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

from utils.name_normalizer import normalize_name

CSV_URL = "https://www2.myfloridalicense.com/sto/file_download/extracts//CONSTRUCTIONLICENSE_1.csv"
DOWNLOAD_TIMEOUT = 300

# Column positions (0-indexed) in the headerless DBPR extract.
C_OCC, C_NAME, C_DBA = 1, 2, 3
C_CITY, C_STATE, C_ZIP = 8, 9, 10
C_LICNUM_NUMERIC = 12
C_PRIMARY, C_SECONDARY = 13, 14
C_ORIG_DATE, C_EXP_DATE = 15, 17
C_FULL_LICNUM = 20


def _map_status(primary: str, secondary: str) -> tuple[str, str]:
    sec = (secondary or "").strip().upper()
    if sec == "I":
        return "licensed_inactive", "Current, Inactive"
    return "licensed_active", "Current, Active"


def _row_to_record(row: list) -> Optional[Dict[str, Any]]:
    if len(row) <= C_FULL_LICNUM:
        return None
    name = (row[C_NAME] or "").strip()
    if not name:
        return None
    dba = (row[C_DBA] or "").strip()
    license_status, _human = _map_status(row[C_PRIMARY], row[C_SECONDARY])
    license_number = (row[C_FULL_LICNUM] or "").strip() or (row[C_LICNUM_NUMERIC] or "").strip()
    return {
        "license_number": license_number,
        "occupation_code": (row[C_OCC] or "").strip(),
        "licensee_name": name,
        "dba_name": dba or None,
        "normalized_name": normalize_name(name),
        "normalized_dba": normalize_name(dba) if dba else None,
        "primary_status": (row[C_PRIMARY] or "").strip(),
        "secondary_status": (row[C_SECONDARY] or "").strip(),
        "license_status": license_status,
        "city": (row[C_CITY] or "").strip() or None,
        "state": (row[C_STATE] or "").strip() or None,
        "zip_code": (row[C_ZIP] or "").strip() or None,
        "original_issue_date": (row[C_ORIG_DATE] or "").strip() or None,
        "expiration_date": (row[C_EXP_DATE] or "").strip() or None,
    }


# ──────────────────────────────────────────────────────────────
# In-process cache
#   _df    — DataFrame (kept around for analysis; queries use _index)
#   _index — dict[normalized_name] -> list[record dict], for O(1) lookups
# Both are populated together inside the lock.
# ──────────────────────────────────────────────────────────────
_df: Optional[pd.DataFrame] = None
_index: Dict[str, List[Dict[str, Any]]] = {}
_dba_index: Dict[str, List[Dict[str, Any]]] = {}
_lock = threading.Lock()


def _build_index(records: List[Dict[str, Any]]) -> None:
    global _df, _index, _dba_index
    _df = pd.DataFrame.from_records(records)
    _index = {}
    _dba_index = {}
    for r in records:
        n = r.get("normalized_name")
        if n:
            _index.setdefault(n, []).append(r)
        d = r.get("normalized_dba")
        if d:
            _dba_index.setdefault(d, []).append(r)


def refresh_dbpr_licenses() -> int:
    """Download the bulk CSV and reload the in-memory index. Returns row count.

    Called once at the start of every pipeline run (see agent/pipeline.py).
    Failures leave the previous index intact so the pipeline can fall back to
    Apify verification per metro instead of stalling.
    """
    print(f"⬇️  [DBPR] downloading {CSV_URL}")
    resp = requests.get(CSV_URL, timeout=DOWNLOAD_TIMEOUT)
    resp.raise_for_status()
    text = resp.content.decode("latin-1")
    reader = csv.reader(io.StringIO(text))

    records: List[Dict[str, Any]] = []
    skipped = 0
    for raw in reader:
        rec = _row_to_record(raw)
        if rec:
            records.append(rec)
        else:
            skipped += 1

    print(f"📊 [DBPR] parsed {len(records)} rows ({skipped} skipped)")

    with _lock:
        _build_index(records)
    print(f"✅ [DBPR] indexed {len(records)} license rows in-memory "
          f"({len(_index)} unique normalized names, {len(_dba_index)} unique normalized DBAs)")
    return len(records)


def _ensure_loaded() -> None:
    """Lazy load — first lookup triggers a download if we never refreshed."""
    if _df is None:
        refresh_dbpr_licenses()


def dbpr_count() -> int:
    if _df is None:
        return 0
    return int(len(_df))


def query_by_normalized_names(normalized_names: List[str]) -> List[Dict[str, Any]]:
    """Return DBPR records whose normalized name OR DBA matches any input."""
    if not normalized_names:
        return []
    _ensure_loaded()
    with _lock:
        results: List[Dict[str, Any]] = []
        seen_ids = set()
        for n in normalized_names:
            for r in _index.get(n, ()):
                key = id(r)
                if key not in seen_ids:
                    seen_ids.add(key)
                    results.append(r)
            for r in _dba_index.get(n, ()):
                key = id(r)
                if key not in seen_ids:
                    seen_ids.add(key)
                    results.append(r)
        return results


def query_dataframe() -> Optional[pd.DataFrame]:
    """Direct DF access for callers that want pandas filtering. Returns None if not loaded."""
    return _df


if __name__ == "__main__":
    n = refresh_dbpr_licenses()
    print(f"Loaded {n} licenses.")
