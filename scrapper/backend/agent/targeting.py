# targeting.py
# Phase 2d — city prioritization: turn the city_tiers + dealer_accounts config
# into tier-ordered SCRAPE UNITS (Tier 1 before Tier 2) and a zip→tier map used to
# tag every record with its city tier.
#
# Two pipelines, two anchors (see the plan):
#   • vendor      → 20 mi around each city center
#   • contractor  → 50 mi around each dealer account (grouped by nearest city)
# Both honour the Memphis-metro territory exclusion (db.is_excluded) before scraping.

from typing import Dict, List, Optional

from agent import db
from agent.geography import (
    zips_within_radius, haversine_miles, contractor_zips_for_dealers,
)

# Radii are user-editable settings (spec: vendor 20 mi, contractor 50 mi) — read
# live so a change in the UI takes effect on the next run, no restart needed.


def _exclude_fn(state: str):
    """A (zip, city) → bool excluder bound to one state's territory rules."""
    return lambda z, city: db.is_excluded(city=city, zip_code=z, state=state)


def vendor_scrape_units(state: str = "TN") -> List[Dict[str, object]]:
    """Tier-ordered vendor targets: one unit per priority city, with the ZIPs inside
    its (20-mi) center radius, territory-excluded zips removed. Tier 1 cities first."""
    excl = _exclude_fn(state)
    radius = db.get_vendor_radius_miles()            # user-editable (default 20 mi)
    units: List[Dict[str, object]] = []
    for c in db.list_city_tiers(state):              # already Tier 1 → Tier 2 ordered
        lat, lng = c.get("center_lat"), c.get("center_lng")
        if lat is None or lng is None:
            continue
        zips = [z for z in zips_within_radius(float(lat), float(lng), float(radius), state=state)
                if not excl(z, c.get("city"))]
        units.append({
            "city": c.get("city"), "tier": c.get("tier"), "state": state,
            "center_lat": lat, "center_lng": lng, "radius_miles": radius, "zips": zips,
        })
    return units


def _nearest_city(lat: float, lng: float, cities: List[Dict[str, object]]) -> Optional[Dict[str, object]]:
    """The priority city closest to a point (used to give a dealer its city tier)."""
    best, best_d = None, None
    for c in cities:
        clat, clng = c.get("center_lat"), c.get("center_lng")
        if clat is None or clng is None:
            continue
        d = haversine_miles(lat, lng, float(clat), float(clng))
        if best_d is None or d < best_d:
            best, best_d = c, d
    return best


def contractor_scrape_units(state: str = "TN", client_id: Optional[str] = None) -> List[Dict[str, object]]:
    """Tier-ordered contractor targets: dealer accounts grouped by their nearest
    priority city; each group's ZIPs are the union within CONTRACTOR_RADIUS_MI (50)
    of its dealers, territory-excluded removed. Ordered Tier 1 city → Tier 2."""
    cities = db.list_city_tiers(state)
    dealers = [d for d in db.list_dealer_accounts(client_id) if (d.get("state") or state).upper() == state.upper()]
    excl = _exclude_fn(state)
    radius = db.get_contractor_radius_miles()        # user-editable (default 50 mi)

    # Bucket dealers under their nearest priority city.
    buckets: Dict[str, List[Dict[str, object]]] = {}
    for d in dealers:
        lat, lng = d.get("lat"), d.get("lng")
        if lat is None or lng is None:
            continue
        nc = _nearest_city(float(lat), float(lng), cities)
        key = (nc or {}).get("city") or "Unassigned"
        buckets.setdefault(key, []).append(d)

    units: List[Dict[str, object]] = []
    for c in cities:                                  # tier order
        city = c.get("city")
        if city not in buckets:
            continue
        zips = contractor_zips_for_dealers(
            buckets[city], radius_miles=radius, state=state, exclude_fn=excl,
        )
        units.append({
            "city": city, "tier": c.get("tier"), "state": state,
            "radius_miles": radius, "dealer_count": len(buckets[city]), "zips": zips,
        })
    return units


def zip_tier_map(state: str = "TN", record_type: str = "vendor",
                 client_id: Optional[str] = None) -> Dict[str, int]:
    """Map every in-territory target ZIP → its city tier (Tier 1 wins on overlap),
    so a scraped record can be tagged with `city_tier` from its zip alone."""
    units = (vendor_scrape_units(state) if record_type == "vendor"
             else contractor_scrape_units(state, client_id))
    mapping: Dict[str, int] = {}
    for u in sorted(units, key=lambda u: u.get("tier") or 99):   # tier 1 first → wins ties
        tier = u.get("tier")
        for z in u.get("zips", []):                              # type: ignore[union-attr]
            mapping.setdefault(z, tier)                          # type: ignore[arg-type]
    return mapping


def city_tier_for_zip(zip_code: str, state: str = "TN", record_type: str = "vendor") -> Optional[int]:
    """City tier (1/2) for a single ZIP, or None if it's outside all target cities."""
    return zip_tier_map(state, record_type).get((zip_code or "").strip()[:5])
