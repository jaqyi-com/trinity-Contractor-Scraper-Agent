# geography.py
# Phase 2c — geography engine (Workstream A).
#
# Pure-Python, no pandas: distance math + a bundled TN/FL ZIP→coordinates table
# (config/zip_coords.csv, from free GeoNames data) + radius→zips computation +
# address geocoding (free local ZIP lookup first, Apify paid actor as fallback).
#
# These are the primitives the contractor (50-mi, dealer-anchored) and vendor
# (20-mi, city-center) pipelines use to turn locations into ZIP sets.

import os
import re
import math
import time
from functools import lru_cache
from typing import List, Optional, Tuple, Dict, Callable

import requests
from dotenv import load_dotenv

from agent.zip_loader import load_zip_rows

load_dotenv()

APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN")
# Paid Apify geocoder actor — used only when a zip can't resolve locally (decided:
# geocoding rides on the existing Apify token). Override via env if you pick another.
APIFY_GEOCODER_ACTOR = os.getenv("APIFY_GEOCODER_ACTOR", "parseforge~uscensus-geocoder-scraper")
APIFY_TIMEOUT = 60
APIFY_GEOCODE_MAX_WAIT = int(os.getenv("APIFY_GEOCODE_MAX_WAIT", "120"))

# States we operate in — the ZIP loader fetches/filters to these.
ZIP_STATES = tuple(s.strip().upper() for s in os.getenv("ZIP_STATES", "TN,FL").split(",") if s.strip())
_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")

EARTH_RADIUS_MI = 3958.7613


# ──────────────────────────────────────────────────────────────
# Distance
# ──────────────────────────────────────────────────────────────
def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in miles between two lat/lng points."""
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2
    return EARTH_RADIUS_MI * 2 * math.asin(math.sqrt(a))


# ──────────────────────────────────────────────────────────────
# ZIP ↔ coordinates table (bundled, loaded once)
# ──────────────────────────────────────────────────────────────
def _zip_table() -> Tuple[Dict[str, object], ...]:
    """ZIP→coords rows for our states — fetched live from GeoNames on demand
    (bundled snapshot fallback), via zip_loader. Cached there per process."""
    return load_zip_rows(ZIP_STATES)


@lru_cache(maxsize=8192)
def zip_to_coords(zip_code: str) -> Optional[Tuple[float, float]]:
    """(lat, lng) for a 5-digit ZIP, or None if not in the bundled table."""
    z = (zip_code or "").strip()[:5]
    for r in _zip_table():
        if r["zip"] == z:
            return (r["lat"], r["lng"])  # type: ignore[return-value]
    return None


def zips_within_radius(
    center_lat: float, center_lng: float, radius_miles: float,
    state: Optional[str] = None,
) -> List[str]:
    """Every ZIP whose center is within radius_miles of (center_lat, center_lng),
    optionally restricted to one state. Sorted nearest-first."""
    hits: List[Tuple[float, str]] = []
    for r in _zip_table():
        if state and r["state"] != state.upper():
            continue
        d = haversine_miles(center_lat, center_lng, r["lat"], r["lng"])  # type: ignore[arg-type]
        if d <= radius_miles:
            hits.append((d, r["zip"]))  # type: ignore[arg-type]
    hits.sort()
    return [z for _, z in hits]


def zip_city(zip_code: str) -> Optional[str]:
    """City name for a ZIP (used by territory-exclusion checks)."""
    z = (zip_code or "").strip()[:5]
    for r in _zip_table():
        if r["zip"] == z:
            return r["city"]  # type: ignore[return-value]
    return None


def zips_for_city(city: str, state: Optional[str] = None) -> List[str]:
    """All ZIP codes whose place name matches `city` (case-insensitive), optionally
    within one state. Used to resolve an excluded city → its ZIPs."""
    name = (city or "").strip().lower()
    if not name:
        return []
    out = []
    for r in _zip_table():
        if state and r["state"] != state.upper():
            continue
        if str(r["city"]).strip().lower() == name:
            out.append(r["zip"])
    return sorted(set(out))  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────
# Geocoding — free local ZIP lookup first, Apify paid actor as fallback
# ──────────────────────────────────────────────────────────────
def geocode_address(address: str) -> Optional[Tuple[float, float]]:
    """Address → (lat, lng). Tries the free bundled ZIP table first (when the
    address contains a known ZIP); falls back to the Apify geocoder actor (paid)."""
    if not address:
        return None
    m = _ZIP_RE.search(address)
    if m:
        coords = zip_to_coords(m.group(1))
        if coords:
            return coords
    return _apify_geocode(address)


def _apify_geocode(address: str) -> Optional[Tuple[float, float]]:
    """Best-effort address→coords via the configured Apify geocoder actor. Returns
    None (never raises) on any failure so callers can degrade gracefully."""
    if not APIFY_API_TOKEN or not APIFY_GEOCODER_ACTOR:
        return None
    base = "https://api.apify.com/v2"
    try:
        run = requests.post(
            f"{base}/acts/{APIFY_GEOCODER_ACTOR}/runs",
            params={"token": APIFY_API_TOKEN},
            json={"addresses": [address]},
            timeout=APIFY_TIMEOUT,
        ).json().get("data", {})
        run_id, dataset_id = run.get("id"), run.get("defaultDatasetId")
        if not run_id:
            return None
        waited = 0
        while waited < APIFY_GEOCODE_MAX_WAIT:
            status = requests.get(
                f"{base}/actor-runs/{run_id}", params={"token": APIFY_API_TOKEN},
                timeout=APIFY_TIMEOUT,
            ).json().get("data", {}).get("status")
            if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                break
            time.sleep(3)
            waited += 3
        items = requests.get(
            f"{base}/datasets/{dataset_id}/items", params={"token": APIFY_API_TOKEN, "limit": 1},
            timeout=APIFY_TIMEOUT,
        ).json()
        if items:
            return _parse_latlng(items[0])
    except (requests.RequestException, ValueError, KeyError) as e:
        print(f"⚠️ [geo] Apify geocode failed for {address!r}: {e}")
    return None


def _parse_latlng(item: dict) -> Optional[Tuple[float, float]]:
    """Pull a (lat, lng) out of a geocoder result row, tolerating key variations."""
    lat_keys = ("lat", "latitude", "Latitude", "y")
    lng_keys = ("lng", "lon", "longitude", "Longitude", "x")
    lat = next((item[k] for k in lat_keys if item.get(k) is not None), None)
    lng = next((item[k] for k in lng_keys if item.get(k) is not None), None)
    if lat is None or lng is None:
        return None
    try:
        return (float(lat), float(lng))
    except (TypeError, ValueError):
        return None


# ──────────────────────────────────────────────────────────────
# Pipeline helpers — turn anchors into target ZIP sets
# ──────────────────────────────────────────────────────────────
def contractor_zips_for_dealers(
    dealers: List[Dict[str, object]],
    radius_miles: float = 50.0,
    state: Optional[str] = None,
    exclude_fn: Optional[Callable[[str, Optional[str]], bool]] = None,
) -> List[str]:
    """Union of ZIPs within `radius_miles` of each dealer account, de-duplicated,
    with territory-excluded ones removed (Phase 2 contractor pipeline).
    Each dealer needs lat/lng (or a zip_code we can resolve). `exclude_fn(zip, city)`
    returns True to drop a ZIP (wired to db.is_excluded by the caller)."""
    seen: Dict[str, None] = {}
    for d in dealers:
        lat, lng = d.get("lat"), d.get("lng")
        if lat is None or lng is None:
            coords = zip_to_coords(str(d.get("zip_code") or ""))
            if not coords:
                continue
            lat, lng = coords
        for z in zips_within_radius(float(lat), float(lng), radius_miles, state=state):  # type: ignore[arg-type]
            if z in seen:
                continue
            if exclude_fn and exclude_fn(z, zip_city(z)):
                continue
            seen[z] = None
    return list(seen.keys())
