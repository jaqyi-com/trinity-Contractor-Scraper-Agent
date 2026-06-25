# Regression + feature tests for the Westpac Sales Scraper upgrade (TN, vendor,
# lumber, data layer). Touches the live Sheets DB (this project's datastore), so
# run against a dev sheet:
#   PYTHONPATH=. ./.venv-test/bin/python tests/test_upgrade.py
#
# Every test cleans up the rows it writes; the 66 real contractors are untouched.

from dotenv import load_dotenv
load_dotenv()

from agent import db
from agent.lumber import check_lumber
from agent.vendor import resolve_vendor_network
from agent import pipeline as P
from agent import geography as G
from agent.scraper_tn_license import is_relevant_classification as tn_relevant

db.init_schema()


# ── FL regression: the upgrade must not change Florida behaviour ──────────────
def test_fl_contractor_no_spurious_reversion():
    """An identical FL contractor re-save must NOT create a new version — proves the
    new tag columns + change-detection ignores don't disturb the versioned save."""
    rec = {"business_name": "ZZ Regression Drywall", "city": "Tampa",
           "zip_code": "33602", "phone": "+18135550000", "tier": "TIER_1_DRYWALL"}
    id1 = db.insert_contractor(rec)
    id2 = db.insert_contractor(rec)
    assert id1 == id2, "FL re-save created a spurious new version!"
    db.get_db().delete("contractors", id1)
    print("✅ FL contractor: identical re-save is a no-op (no spurious version)")


def test_fl_run_plan_unchanged():
    """Default (contractor/FL) run plan: FL cities ONLY (not TN) + contractor queries.
    Guards the regression where TN cities (now in the same cities tab) leaked into FL runs."""
    plan = P._resolve_run_plan("contractor", "FL")
    assert plan["state"] == "FL" and plan["queries"] is None and plan["record_type"] == "contractor"
    fl_only = [c for c in db.list_cities() if (c.get("state") or "FL").upper() == "FL"]
    assert len(plan["cities"]) == len(fl_only), "FL plan should contain only FL cities!"
    assert all((c.get("state") or "FL").upper() == "FL" for c in plan["cities"]), "TN city leaked into FL plan!"
    print(f"✅ FL run plan = FL cities only ({len(plan['cities'])} cities), no TN leak")


# ── Territory: Memphis hard-exclusion ────────────────────────────────────────
def test_memphis_excluded():
    assert db.is_excluded(city="Memphis", state="TN") is True
    assert db.is_excluded(city="Bartlett", state="TN") is True
    assert db.is_excluded(city="Nashville", state="TN") is False
    print("✅ Memphis metro excluded; Nashville in-territory")


# ── Lumber 3-layer filter (flag, don't delete) ───────────────────────────────
def test_lumber_filter():
    assert check_lumber({"business_name": "Smith Lumber Co"}) is not None
    assert check_lumber({"business_name": "X", "google_categories": ["lumber_store"]}) is not None
    assert check_lumber({"business_name": "X", "description": "we sell lumber"}) is not None
    assert check_lumber({"business_name": "Reliable Plumber", "google_categories": ["plumber"]}) is None
    assert check_lumber({"business_name": "Music City Drywall"}) is None
    print("✅ lumber filter: lumber flagged, plumber/drywall clean")


# ── Vendor alias roll-up ─────────────────────────────────────────────────────
def test_vendor_rollup():
    for brand in ("Tucker Materials", "Gator Gypsum", "Rocky Top Materials", "Drywall Supply"):
        assert resolve_vendor_network(brand)["canonical_network"] == "GMS", brand
    assert resolve_vendor_network("ABC Supply Interiors")["canonical_network"] == "L&W Supply"
    assert resolve_vendor_network("The Home Depot")["vendor_type"] == "big_box_retailer"
    assert resolve_vendor_network("Joe Random Dealer") is None
    print("✅ vendor roll-up: GMS brands → one network; big-box flagged")


# ── Entity resolution + idempotent upsert ────────────────────────────────────
def test_entity_resolution_and_upsert():
    a = {"business_name": "ZZ Up Drywall LLC", "city": "Nashville", "zip_code": "37201", "phone": "+16155551111"}
    b = {"business_name": "ZZ Up Drywall, Inc", "city": "Nashville", "zip_code": "37201"}  # no phone
    assert db.compute_canonical_entity_id(a) == db.compute_canonical_entity_id(b), "phone split entities!"
    cid1 = db.upsert_contractor(a, source="google_business")
    cid2 = db.upsert_contractor(b, source="bbb")
    assert cid1 == cid2, "same business made two rows!"
    row = db.get_db().get_by_id("contractors", cid1)
    assert set(["google_business", "bbb"]).issubset(set(row.get("sources") or []))
    # cleanup row + its source_records
    db.get_db().delete("contractors", cid1)
    for s in db.list_source_records(row["canonical_entity_id"]):
        db.get_db().delete("source_records", s["id"])
    print("✅ entity resolution: name+loc merges sources into one idempotent row")


# ── Geography: distance + radius→zips + dealer exclusion ──────────────────────
def test_geography():
    d = G.haversine_miles(36.1627, -86.7816, 35.9606, -83.9207)
    assert 140 < d < 190, f"Nashville→Knoxville distance off: {d}"
    near = G.zips_within_radius(36.1627, -86.7816, 20, state="TN")
    assert len(near) > 20, "too few zips near Nashville"
    excl = lambda z, city: db.is_excluded(city=city, zip_code=z, state="TN")
    memphis = G.contractor_zips_for_dealers([{"lat": 35.1495, "lng": -90.0490}],
                                            radius_miles=10, state="TN", exclude_fn=excl)
    assert memphis == [], "Memphis dealer should yield zero in-territory zips"
    print("✅ geography: distance, radius→zips, Memphis dealer excluded")


# ── TN license: filter by classification, not the word "drywall" ─────────────
def test_tn_license_classification_filter():
    """In-scope building/GC/drywall-trade classifications pass; unrelated trades
    (plumbing/electrical/roofing/septic) are dropped — even though none literally
    say 'drywall'. This is the spec's 'filter by classification, not keyword'."""
    for cls in ("General Contractor License", "State Residential Building",
                "State Carpentry, Framming And Millwork", "State Masonry",
                "State Painting, Interior Decorating", "  general contractor LICENSE "):
        assert tn_relevant(cls) is True, cls
    for cls in ("State Plumbing Contractor", "State Electrical Contractor",
                "State Roofing", "Septic Tank Installation", ""):
        assert tn_relevant(cls) is False, cls
    print("✅ TN license: in-scope classifications kept; off-scope trades dropped")


# ── Gap fixes (audit follow-up) ──────────────────────────────────────────────
def test_export_deliverable_drops_flagged():
    """The export/deliverable view must drop lumber-excluded + out-of-territory rows
    by default, and include them only when explicitly asked (audit)."""
    from datetime import datetime
    d = db.get_db()
    for r in d.find("contractors", lambda r: r.get("client_id") == "ZZGAP"):
        d.delete("contractors", r["id"])
    mk = lambda **k: d.insert("contractors", {"client_id": "ZZGAP", "record_type": "contractor",
                                               "scraped_at": datetime.utcnow(), **k})
    a = mk(business_name="ZZ Clean")
    b = mk(business_name="ZZ Lumber", excluded_reason="lumber:keyword:lumber")
    c = mk(business_name="ZZ Memphis", out_of_territory=True)
    deliver = list(db.iter_contractors_filtered({"client_id": "ZZGAP"}))
    audit = list(db.iter_contractors_filtered({"client_id": "ZZGAP", "include_excluded": True,
                                               "include_out_of_territory": True}))
    for x in (a, b, c):
        d.delete("contractors", x["id"])
    assert len(deliver) == 1 and len(audit) == 3, (len(deliver), len(audit))
    print("✅ export deliverable drops flagged by default; audit shows all")


def test_save_writes_source_records():
    """The save path writes the raw per-source provenance layer (one source_records
    row per source) linked by canonical_entity_id (Workstream E)."""
    rec = {"business_name": "ZZ Prov Co", "city": "Nashville", "zip_code": "37201",
           "state": "TN", "sources": ["google_business", "bbb"], "record_type": "contractor"}
    ceid = db.compute_canonical_entity_id(rec)
    d = db.get_db()
    for r in db.list_source_records(ceid):
        d.delete("source_records", r["id"])
    cid = db.insert_contractor(rec)
    for src in rec["sources"]:
        db.record_source(rec, src, run_id="jobT")
    srcs = db.list_source_records(ceid)
    d.delete("contractors", cid)
    for s in srcs:
        d.delete("source_records", s["id"])
    assert {s["source"] for s in srcs} == {"google_business", "bbb"}
    print("✅ save writes per-source raw provenance rows")


def test_bbb_category_lumber():
    """Lumber Layer 1 catches a lumber category that only BBB reports (clean Google
    category, lumber BBB category)."""
    google = ["general_contractor"]
    bbb_cats = ["Lumber", "Building Materials"]
    assert check_lumber({"business_name": "ABC Building", "google_categories": google}) is None
    assert check_lumber({"business_name": "ABC Building",
                         "google_categories": google + bbb_cats}) is not None
    print("✅ lumber Layer 1 catches BBB-reported lumber category")


def test_vendor_seed_loader():
    """The vendor seed xlsx loads into GoogleSeeds tagged 'vendor_seed', with alias
    roll-up applied (Tucker Materials -> GMS)."""
    import os, tempfile
    from openpyxl import Workbook
    from agent.scraper_vendor import seed_distributor_seeds
    from agent import pipeline as P
    wb = Workbook(); ws = wb.active
    ws.append(["name", "address", "phone", "city", "notes"])
    ws.append(["Tucker Materials", "100 Main St", "615-555-0001", "Nashville", "GMS branch"])
    p = tempfile.mktemp(suffix=".xlsx"); wb.save(p)
    try:
        seeds = seed_distributor_seeds(p)
        rows = P._vendor_rows_from_seeds(seeds, "TN", "westpac", "jobS")
        assert len(seeds) == 1 and seeds[0].place_id.startswith("seed:")
        assert rows[0].sources == ["vendor_seed"] and rows[0].canonical_network == "GMS"
        assert seed_distributor_seeds("/nonexistent.xlsx") == []  # graceful
    finally:
        os.remove(p)
    print("✅ vendor seed xlsx → seeds tagged 'vendor_seed' + GMS roll-up; graceful when absent")


def test_tdci_roster_fallback():
    """TDCI statewide roster loads from a configured file (flexible columns), matches
    by name, skips already-matched names, and is graceful when no file is set."""
    import os, tempfile
    from agent import scraper_tdci as T
    from agent.schema import GoogleSeed, DBPRLicense
    # graceful: no roster
    T.TDCI_ROSTER_FILE = ""; T.load_tdci_roster.cache_clear()
    assert T.fetch_tdci_licenses_for_seeds([GoogleSeed(place_id="x", business_name="Foo", city="Nashville")]) == []
    # with a roster file
    p = tempfile.mktemp(suffix=".csv")
    open(p, "w").write("Business Name,Classification,City,State,Zip\n"
                       "ZZ TDCI Drywall LLC,General Contractor,Knoxville,TN,37902\n")
    T.TDCI_ROSTER_FILE = p; T.load_tdci_roster.cache_clear()
    try:
        seed = GoogleSeed(place_id="s1", business_name="ZZ TDCI Drywall, Inc", city="Knoxville")
        lics = T.fetch_tdci_licenses_for_seeds([seed])
        assert len(lics) == 1 and lics[0].license_category == "General Contractor"
        already = [DBPRLicense(license_number="", license_category="x",
                               licensee_name="ZZ TDCI Drywall LLC", status="Current, Active")]
        assert T.fetch_tdci_licenses_for_seeds([seed], already=already) == []  # skip matched
    finally:
        os.remove(p); T.TDCI_ROSTER_FILE = ""; T.load_tdci_roster.cache_clear()
    print("✅ TDCI roster fallback: loads, name-matches, skips matched, graceful when absent")


if __name__ == "__main__":
    test_fl_contractor_no_spurious_reversion()
    test_fl_run_plan_unchanged()
    test_memphis_excluded()
    test_lumber_filter()
    test_vendor_rollup()
    test_entity_resolution_and_upsert()
    test_geography()
    test_tn_license_classification_filter()
    # audit gap-fix tests
    test_export_deliverable_drops_flagged()
    test_save_writes_source_records()
    test_bbb_category_lumber()
    test_vendor_seed_loader()
    test_tdci_roster_fallback()
    print("\n🎉 all upgrade regression + feature tests passed")
