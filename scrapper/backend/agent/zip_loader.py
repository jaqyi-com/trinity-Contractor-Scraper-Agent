# zip_loader.py
# Live ZIP→coordinates loader — mirrors the dbpr_loader pattern: fetch the
# authoritative dataset on demand instead of hardcoding it, so the data is fresh
# and the source of truth is GeoNames (not a stale file checked into the repo).
#
# How it works:
#   On first use per process we download GeoNames' US postal-code archive
#   (US.zip, ~0.6 MB), unzip it in memory, and keep ONLY the rows for the states
#   we operate in (TN/FL by default). Cached in-process (lru_cache) so a pipeline
#   run downloads once, not per call. Peak memory ≈ the filtered rows (a few MB).
#
# Difference from DBPR (intentional): ZIP/coords are essentially static and the
# loader runs in the DISCOVERY stage, so a GeoNames outage would block scraping.
# To stay resilient we fall back to the bundled config/zip_coords.csv snapshot if
# the live download fails. Live data wins; the snapshot is only a safety net.

import csv
import io
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Tuple

import requests

GEONAMES_URL = "https://download.geonames.org/export/zip/US.zip"
DOWNLOAD_TIMEOUT = 120

# GeoNames US.txt is headerless, tab-separated. Column positions:
C_STATE_CODE = 4      # 'TN' / 'FL'
C_POSTAL, C_CITY, C_COUNTY = 1, 2, 5
C_LAT, C_LNG = 9, 10

# Bundled offline fallback (a frozen GeoNames snapshot for TN+FL).
_FALLBACK_CSV = Path(__file__).resolve().parent.parent / "config" / "zip_coords.csv"

_last_source = "none"   # 'geonames' | 'fallback' — surfaced for diagnostics


def _from_geonames(states: frozenset) -> List[Dict[str, object]]:
    """Download + unzip GeoNames US.zip and return rows for the requested states."""
    resp = requests.get(GEONAMES_URL, timeout=DOWNLOAD_TIMEOUT)
    resp.raise_for_status()
    rows: List[Dict[str, object]] = []
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        with zf.open("US.txt") as fh:
            for raw in io.TextIOWrapper(fh, encoding="utf-8"):
                p = raw.rstrip("\n").split("\t")
                if len(p) <= C_LNG:
                    continue
                if p[C_STATE_CODE] not in states:
                    continue
                try:
                    rows.append({
                        "zip": p[C_POSTAL], "state": p[C_STATE_CODE], "city": p[C_CITY],
                        "county": p[C_COUNTY], "lat": float(p[C_LAT]), "lng": float(p[C_LNG]),
                    })
                except (ValueError, IndexError):
                    continue
    return rows


def _from_fallback(states: frozenset) -> List[Dict[str, object]]:
    """Read the bundled CSV snapshot (offline safety net)."""
    rows: List[Dict[str, object]] = []
    if not _FALLBACK_CSV.exists():
        return rows
    with open(_FALLBACK_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("state") not in states:
                continue
            try:
                rows.append({
                    "zip": r["zip"], "state": r["state"], "city": r["city"],
                    "county": r["county"], "lat": float(r["lat"]), "lng": float(r["lng"]),
                })
            except (ValueError, KeyError):
                continue
    return rows


@lru_cache(maxsize=8)
def load_zip_rows(states: Tuple[str, ...] = ("TN", "FL")) -> Tuple[Dict[str, object], ...]:
    """ZIP→coords rows for the given states. Tries live GeoNames first; falls back
    to the bundled snapshot on any download/parse failure. Cached per process."""
    global _last_source
    want = frozenset(s.upper() for s in states)
    try:
        rows = _from_geonames(want)
        if rows:
            _last_source = "geonames"
            print(f"⬇️  [zip] GeoNames live: {len(rows)} rows for {sorted(want)}")
            return tuple(rows)
    except (requests.RequestException, zipfile.BadZipFile, KeyError) as e:
        print(f"⚠️  [zip] GeoNames fetch failed ({e}) — using bundled snapshot")
    rows = _from_fallback(want)
    _last_source = "fallback"
    print(f"📁 [zip] bundled snapshot: {len(rows)} rows for {sorted(want)}")
    return tuple(rows)


def zip_source() -> str:
    """Where the most recent load came from ('geonames' | 'fallback' | 'none')."""
    return _last_source


if __name__ == "__main__":
    rows = load_zip_rows(("TN", "FL"))
    print(f"loaded {len(rows)} rows from {zip_source()}")
