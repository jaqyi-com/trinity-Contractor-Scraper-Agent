# dbpr_loader.py
# Streaming DBPR licensee lookup — low-memory replacement for the old
# "load all 266k rows into a pandas DataFrame + dict index" approach.
#
# Why the rewrite:
#   The old loader downloaded the ~266k-row Florida CSV and built BOTH a pandas
#   DataFrame AND two dict indexes in process memory (~700MB–1GB). On a 512MB
#   container that OOM-crashed exactly at the DBPR stage.
#
# How it works now:
#   The pipeline only ever needs to match the (capped, ~5k) discovered business
#   names against DBPR. So instead of indexing all 266k rows, we STREAM the CSV
#   once and keep ONLY the rows whose normalized name/DBA is in the requested
#   set. Peak memory ≈ the target name set + the handful of matched records
#   (a few MB), never the whole file.
#
# Sheets is intentionally NOT used for DBPR: 266k rows would also blow the
# in-memory sheet mirror (see sheets_client._load_mirror). The official CSV,
# streamed on demand, is both fresher and cheaper.

import csv
from typing import Any, Dict, List, Optional

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

# Last-stream stats — exposed via dbpr_count() for the health endpoint. Lives
# only in memory; reset on every query. Never holds row data.
_last_scanned = 0
_last_matched = 0


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


def _stream_rows():
    """Yield raw CSV rows one at a time without buffering the whole file.

    iter_lines() streams the response body line-by-line; each line is decoded
    latin-1 (the extract's encoding) and fed to csv.reader so quoted commas in
    names/addresses are handled. The DBPR extract puts one record per physical
    line (no embedded newlines), so line-by-line parsing is safe.
    """
    resp = requests.get(CSV_URL, stream=True, timeout=DOWNLOAD_TIMEOUT)
    resp.raise_for_status()
    lines = (raw.decode("latin-1") for raw in resp.iter_lines() if raw)
    yield from csv.reader(lines)


def query_by_normalized_names(normalized_names: List[str]) -> List[Dict[str, Any]]:
    """Stream the DBPR CSV and return records whose normalized name OR DBA
    matches any input. Memory stays bounded: only matches are retained.

    Called once per pipeline run from the License Match stage
    (scraper_dbpr.fetch_licenses_for_seeds → db.query_dbpr_by_names).
    """
    global _last_scanned, _last_matched
    targets = {n for n in normalized_names if n}
    if not targets:
        return []

    print(f"⬇️  [DBPR] streaming {CSV_URL} — matching {len(targets)} names")
    results: List[Dict[str, Any]] = []
    scanned = 0
    for raw in _stream_rows():
        scanned += 1
        if len(raw) <= C_FULL_LICNUM:
            continue
        name = (raw[C_NAME] or "").strip()
        if not name:
            continue
        # Normalize only the match keys up front; build the full record only on a hit.
        nn = normalize_name(name)
        dba = (raw[C_DBA] or "").strip()
        nd = normalize_name(dba) if dba else None
        if nn in targets or (nd and nd in targets):
            rec = _row_to_record(raw)
            if rec:
                results.append(rec)

    _last_scanned = scanned
    _last_matched = len(results)
    print(f"✅ [DBPR] scanned {scanned} rows, matched {len(results)} license records "
          f"({len(targets)} names requested)")
    return results


def dbpr_count() -> int:
    """Rows scanned in the most recent stream (0 before the first query).
    Kept for the health endpoint / back-compat — holds no row data."""
    return _last_scanned


if __name__ == "__main__":
    # Smoke test: match a couple of known names without loading the whole file.
    hits = query_by_normalized_names([normalize_name("CRACCHIOLO, SAM A JR")])
    print(f"Matched {len(hits)} record(s).")
    for h in hits[:3]:
        print(h)
