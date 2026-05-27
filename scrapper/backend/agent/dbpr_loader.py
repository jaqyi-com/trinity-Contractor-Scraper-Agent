# dbpr_loader.py
# Downloads the free, official Florida DBPR construction-licensee bulk CSV and
# full-replaces the dbpr_licenses table. The pipeline calls refresh_dbpr_licenses()
# at the start of every run (see agent/pipeline.py), so the bulk table is always
# fresh — there is no separate cron/scheduler. Can also be run standalone:
#   python -m agent.dbpr_loader
#
# The file lists ~266k construction licensees, quote/comma delimited, NO header.
# It includes Active / Inactive / voluntarily-inactive; it EXCLUDES Null&Void,
# delinquent, and involuntarily-inactive records (those fall back to the Apify
# verifier in scraper_dbpr.py).

import csv
import io

import requests

from agent.db import init_schema, replace_dbpr_licenses
from utils.name_normalizer import normalize_name

CSV_URL = "https://www2.myfloridalicense.com/sto/file_download/extracts//CONSTRUCTIONLICENSE_1.csv"
DOWNLOAD_TIMEOUT = 300

# Column positions (0-indexed) in the headerless extract.
C_OCC, C_NAME, C_DBA = 1, 2, 3
C_CITY, C_STATE, C_ZIP = 8, 9, 10
C_LICNUM_NUMERIC = 12
C_PRIMARY, C_SECONDARY = 13, 14
C_ORIG_DATE, C_EXP_DATE = 15, 17
C_FULL_LICNUM = 20


def _map_status(primary: str, secondary: str) -> tuple[str, str]:
    """
    Return (license_status, human_status_string).
    Secondary status is the active/inactive signal; the bulk file only contains
    good-standing licenses, so an empty secondary is treated as active.
    """
    sec = (secondary or "").strip().upper()
    if sec == "I":
        return "licensed_inactive", "Current, Inactive"
    # "A" or "" → active/current
    return "licensed_active", "Current, Active"


def _row_to_tuple(row: list) -> tuple | None:
    if len(row) <= C_FULL_LICNUM:
        return None
    name = (row[C_NAME] or "").strip()
    if not name:
        return None

    dba = (row[C_DBA] or "").strip()
    license_status, _human = _map_status(row[C_PRIMARY], row[C_SECONDARY])
    license_number = (row[C_FULL_LICNUM] or "").strip() or (row[C_LICNUM_NUMERIC] or "").strip()

    return (
        license_number,
        (row[C_OCC] or "").strip(),
        name,
        dba or None,
        normalize_name(name),
        normalize_name(dba) if dba else None,
        (row[C_PRIMARY] or "").strip(),
        (row[C_SECONDARY] or "").strip(),
        license_status,
        (row[C_CITY] or "").strip() or None,
        (row[C_STATE] or "").strip() or None,
        (row[C_ZIP] or "").strip() or None,
        (row[C_ORIG_DATE] or "").strip() or None,
        (row[C_EXP_DATE] or "").strip() or None,
    )


def refresh_dbpr_licenses() -> int:
    """Download the bulk CSV and full-replace the dbpr_licenses table."""
    init_schema()
    print(f"⬇️  [DBPR] downloading {CSV_URL}")
    resp = requests.get(CSV_URL, timeout=DOWNLOAD_TIMEOUT)
    resp.raise_for_status()

    text = resp.content.decode("latin-1")  # DBPR extracts are latin-1, not utf-8
    reader = csv.reader(io.StringIO(text))

    rows: list[tuple] = []
    skipped = 0
    for raw in reader:
        t = _row_to_tuple(raw)
        if t:
            rows.append(t)
        else:
            skipped += 1

    print(f"📊 [DBPR] parsed {len(rows)} rows ({skipped} skipped)")
    n = replace_dbpr_licenses(rows)
    print(f"✅ [DBPR] loaded {n} license rows into dbpr_licenses")
    return n


if __name__ == "__main__":
    refresh_dbpr_licenses()
