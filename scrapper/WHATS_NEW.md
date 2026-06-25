# Westpac Sales Scraper — What's New (Upgrade Summary)

**Branch:** `feat/westpac-tn-vendor-lumber-data-layer`
**Spec:** `Scraper_Platform_Upgrade_Dev_Checklist.md.pdf`
**Golden rule:** Fully **additive** — existing **Florida contractor** behaviour is unchanged (regression-tested).

This release upgrades the old *Contractor Scraper* (Florida-only) into the **Westpac Sales Scraper** — now multi-territory, multi-record-type, with a clean staged data layer.

---

## 1. The big picture — what changed

| Before | After |
|---|---|
| Florida only | **Florida + Tennessee** |
| Contractors only | **Contractors + Vendors (distributors)** |
| Hardcoded cities | **Editable cities/zips/tiers/radii/exclusions** (UI) |
| Keyword-only lumber exclude (failing) | **3-layer lumber filter** (flag, don't delete) |
| Flat results table | **Staged, tagged data layer** + per-stage views |

Same infrastructure as before — **Apify** (discovery/BBB), **Apollo** (enrichment), **Google Sheets** (datastore). **No new paid service** was added (geocoding rides on the existing Apify token).

---

## 2. The new run flow

When you click **Start**, you now choose **What** (Contractors / Vendors) and **Where** (Florida / Tennessee). The pipeline picks the right plan automatically:

```
                         ┌─────────────────────────────────────────────┐
   Florida + Contractor  │ existing FL city list → discover → ...       │  (UNCHANGED)
                         └─────────────────────────────────────────────┘

                         ┌─────────────────────────────────────────────┐
   Tennessee + Contractor│ Case 1: dealer accounts exist?               │
                         │   → 50 mi around each dealer → zips           │
                         │ Case 2: no dealer accounts?                   │
                         │   → TN city zips (Florida-style)              │
                         │ (Memphis always excluded; Tier 1 cities first)│
                         └─────────────────────────────────────────────┘

                         ┌─────────────────────────────────────────────┐
   Tennessee + Vendor    │ 20 mi around each priority city center       │
                         │ → distributors → roll up to one network (GMS) │
                         └─────────────────────────────────────────────┘
```

**Every run goes through 5 pipeline stages (snapshotted for audit):**

```
1. Discovery   → raw businesses from Google Maps
2. Dedupe      → duplicates collapsed (before paid enrichment)
3. Classify    → tier assigned + lumber/territory flags applied
4. Cap         → keep the strongest N leads
5. Enrich+Save → license (DBPR/TN) + BBB + Apollo, then saved
```

**Two search radii (both editable in Settings):**
- **Vendor radius = 20 mi** → used when scraping **vendors**, around each **city center**.
- **Contractor radius = 50 mi** → used when scraping **TN contractors**, around each **vendor/dealer account**.

---

## 3. What's new, workstream by workstream

### A — Geography & Territory
- **Tennessee added** alongside Florida — TN cities + ZIPs live in the same editable Cities tab, tagged `TN`.
- **City prioritization:** Tier 1 named cities (Pigeon Forge, Nashville, Chattanooga, Jackson, Columbia, Knoxville) scraped **first**; Tier 2 = other TN cities ≥ 50k. Every record gets a **tier tag**.
- **Memphis metro hard-exclusion** — Memphis, Bartlett, Germantown, Collierville, etc. are **never scraped or returned**. Locked (can't be removed); resolves to actual ZIP codes.
- **Two editable radii** (vendor 20 / contractor 50 mi).
- **Geocoding** (address → coordinates) via Apify; **ZIP↔coordinates** data (free GeoNames, fetched live with a bundled fallback).
- **Dealer-anchored zips:** for TN contractors, compute all ZIPs within 50 mi of each dealer account, dedupe, drop excluded.

### B — Contractor scraper (Tennessee)
- Existing **search + classifier logic reused unchanged**.
- **TN license verification** (validation/enrichment, not discovery), in priority order:
  1. **Nashville open data** ("Registered Professional Contractors", live)
  2. **TDCI statewide roster** (loaded from an open-records export file — fallback)
  3. **verify.tn.gov** per-name lookup (optional, off by default)
- License matched by **trade classification** (not the word "drywall"), as the spec requires.
- **State-aware routing:** Florida → DBPR; Tennessee → the TN sources above.

### C — Vendor scraper (new mode)
- A **separate scrape mode** for drywall-material **distributors**.
- Anchored on priority city centers (20 mi radius).
- **Vendor alias roll-up:** branch/brand names collapse to one network — e.g. *Tucker Materials / Gator Gypsum / Rocky Top Materials / Drywall Supply → **GMS***; *ABC Supply / ABC Supply Interiors → **L&W Supply***.
- **Big-box retailers** (Home Depot / Lowe's) are kept but **flagged** (`is_big_box`).
- **Seed list** (`Nashville_Drywall_Distributors.xlsx`) folds in as a validation/seed set when provided.

### D — Lumber exclusion (3 layers, flag don't delete)
A single "exclude the word lumber" rule was insufficient, so:
1. **Category** — Google Maps **and BBB** category indicating lumber/sawmill/lumberyard.
2. **Negative-keyword list** — editable terms on name + description.
3. **Name-pattern** — regex catches a lumber-signaling name with a clean category.
- Applied to **both** contractor and vendor pipelines.
- **Flag, don't delete:** lumber rows are kept with an `excluded_reason` (auditable) and **dropped from the deliverable/export** automatically.

### E — Data separation & access layer
- **Staged pipeline:** each phase's record set is snapshotted (viewable per batch).
- **Tagged records:** `client_id`, `record_type`, `state`, `city`, `tier`, `zip`, `county`, `source`, `scrape_run_id`, `canonical_entity_id`, status flags (`out_of_territory`, `excluded_reason`, `enrichment_status`).
- **Entity resolution:** one `canonical_entity_id` per real business (this is how GMS branches and L&W/ABC merge).
- **Raw provenance layer:** every source (Google/BBB/license) is logged immutably, linked to its canonical business.
- **Reference tables** (config ≠ scraped data): territories, city tiers, vendor aliases, negative keywords, dealer accounts — all UI-editable.
- **Derived deliverable:** the export applies territory + lumber + tier filters **at request time** (underlying data stays wide).

---

## 4. New UI (left nav)

| Page | What it does |
|---|---|
| **Dashboard** | Pick mode + territory; Settings (max records, cost budgets, **radii**); live run progress. Rebranded "Westpac Sales Scraper". |
| **Cities** | FL and TN in separate sections; TN shows **Tier 1 / Tier 2** sub-groups + an **Excluded Regions** panel (Memphis locked; add more via dropdown). |
| **Dealer Accounts** | Manage vendor/dealer locations (geocoded) — anchors for the TN contractor radius. |
| **Vendor Aliases** | Manage the brand → network roll-up map. |
| **Pipeline Stages** | Per batch, view records at each stage (Discovery → Dedupe → Classify → Cap → Enrich). |
| **Results** | Filter by record type / territory / tier; export. |

---

## 5. New code (backend)

| Area | Files |
|---|---|
| Geography engine | `agent/geography.py`, `agent/zip_loader.py`, `agent/targeting.py` |
| TN license | `agent/scraper_tn_license.py`, `agent/scraper_tdci.py`, `agent/verify_tn.py` |
| Vendor | `agent/scraper_vendor.py`, `agent/vendor.py` |
| Lumber filter | `agent/lumber.py` |
| Config (editable seeds) | `config/tennessee.yaml`, `config/vendor_aliases.yaml`, `config/negative_keywords.yaml`, `config/zip_coords.csv` |
| New API routes | `api/routes/stages.py`, `dealers.py`, `vendor_aliases.py`, `exclusions.py` |
| Data layer | extended `agent/db.py`, `agent/sheets_schema.py` (new tabs + tags) |

---

## 6. Quality / safety

- **13 / 13** upgrade regression + feature tests pass (`tests/test_upgrade.py`).
- **Florida is regression-guarded** — an identical FL re-run produces identical results, FL run scopes to FL cities only.
- **Secrets** (`.env`, Google service-account JSON) are gitignored — never pushed.

### Decisions taken (with stakeholder)
- **Single-client** for now (`client_id` field present so multi-client is a config change later).
- **Datastore stays Google Sheets** (no new database).
- **Vendor scraping is Tennessee-only** (per spec).

### Known / pending
- A full **live end-to-end scrape** on real Apify credits has not been run yet (verified via sample data + tests).
- TDCI roster + vendor seed `.xlsx` activate once those files are provided.
- Multi-client isolation + data-retention policy deferred (single-client decision).
