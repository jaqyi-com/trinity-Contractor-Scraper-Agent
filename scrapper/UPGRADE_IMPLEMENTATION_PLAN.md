# Scraper Platform Upgrade — Detailed Implementation Plan

> Source spec: `Scraper_Platform_Upgrade_Dev_Checklist.md.pdf` + client message (additional requirements below).
> Golden rule: **Additive only.** Florida behavior must keep working unchanged.
> Build order (from spec): **A → E → B → C**, with **D** applied across B and C.
> Execution: one (sub-)phase at a time, start at Phase 0. After each sub-phase: a short plain-English summary + a test against `backend/.env`. Proceed only on "next".

---

## Additional requirements (from client message, beyond the PDF)

These refine/extend the spec — folded into the phases below.

1. **App rebrand: "Contractor Scraper" → "Westpac Sales Scraper".** The product now scrapes TWO record types: contractors AND vendors. Rebrand UI titles, headers, README, page copy. (→ Phase 6A.)

2. **"Vendors" = physical locations that buy bulk construction materials and resell to contractors** — "a grocery store for construction materials" (drywall-material distributors / dealers). This is the new `record_type=vendor`. (→ Phase 4.)

3. **Dealer-account-anchored contractor radius (TN).** The contractor scraper's 50-mile radius is anchored on the client's **dealer/vendor account locations**, not just city centers. Example: *Home Depot is in zip X → scrape contractors within 50 miles of that Home Depot.* So we need a `dealer_accounts` input list (addresses) → geocode → 50-mi zip set → territory-exclude → scrape. (→ Phase 1C + Phase 2C.)

### Important — two SEPARATE anchor concepts (don't confuse)
- **Contractor scraper anchor** = **dealer/vendor account locations** (the client's accounts, may include Home Depot), radius **50 mi**. ← additional requirement #3.
- **Vendor scraper anchor** = **prioritized city centers**, radius **20 mi**. ← PDF Workstream C.
- The earlier "big-box are NOT anchors" note applies ONLY to the *vendor* scraper. As a *dealer account*, a Home Depot legitimately anchors the *contractor* radius. As a *vendor record* in output it is kept but flagged `is_big_box`.

---

## 0. Current system (what we already have)

| Area | File(s) | Today's state |
|---|---|---|
| Orchestrator | `agent/pipeline.py` | 6 phases: discovery → dedupe_seeds → classify → cap → enrich+save → dedupe_final. Stop/resume via checkpoints. |
| Discovery | `agent/scraper_google.py` | Apify Google Maps actor, zip-driven, returns `GoogleSeed`. |
| License (FL) | `agent/scraper_dbpr.py`, `dbpr_loader.py` | Streams FL DBPR ~266k-row CSV. **FL-only.** |
| BBB / Email | `agent/scraper_bbb.py`, `enrichment.py` | Apify BBB + Apollo email/owner. |
| Classifier | `agent/classifier.py`, `keywords.py` | Keyword tiers from DB. `EXCLUDE_HARD`/`EXCLUDE_SOLO` only (keyword-only). |
| Dedupe | `agent/dedupe.py`, `matcher.py` | `dedupe_key` based. |
| Storage | `agent/db.py`, `sheets_client.py`, `sheets_schema.py` | **Google Sheets** datastore. Single `contractors` tab + versioned batches. |
| Geography | `config/cities.yaml`, `cities`/`city_zips` tabs | **FL only.** Flat name+state+zips. No tier/coords/radius/county/exclusion. |
| Schema | `agent/schema.py` | `GoogleSeed`, `ContractorRow`, etc. No `record_type`/`excluded_reason`/`canonical_entity_id`/`client_id`. |
| API / UI | `api/`, `frontend/` | FastAPI + React. Dashboard/Keywords/Results/Cities/Logs/History. |
| Resources | `.env.example` | Apify, Apollo, Google Sheets SA, JWT. |

---

## Phase 0 — Decisions & setup (BLOCKER, do first)

These are business decisions from the spec §3; they shape everything below.

### DECIDED
- [x] **Big-box anchors (HD / Lowe's):** **Keep them, don't drop.** Do NOT use them as radius anchors (anchors = prioritized city list only). When a Home Depot / Lowe's surfaces in vendor discovery, **flag it** with `is_big_box = true` (and/or `vendor_type = big_box_retailer`) instead of excluding it. Deliverable/export can then filter big-box in or out per request.
- [x] **License-data depth:** Use the **free Nashville open data** path now (Workstream B priority #1). TDCI open-records roster is **deferred** (optional, add later only if needed). License stays validation/enrichment, never primary discovery.
- [x] **Vendor roll-up:** Follow the spec exactly — **all GMS subsidiary brands roll up to a single "GMS" entity** in output (Drywall Supply, Tucker Materials, Gator Gypsum, Rocky Top Materials, …). Same for L&W ↔ ABC Supply. Implemented via the `vendor_aliases` reference table (alias → canonical network).

- [x] **Tenancy model:** **SINGLE-CLIENT.** Build for one client now. But still add a `client_id` field on records (default to one seeded client) so future multi-client is a config change, not a refactor. Workstream E isolation can stay simple (no RLS / per-client schema needed now).
- [x] **Datastore:** **Stay on Google Sheets.** No Postgres/Supabase. The staged-layer + tagging model from Workstream E is implemented as additional Sheets tabs + record tags (not a new DB).
- [x] **Geocoding:** Use an **Apify paid actor** for address → coordinates (no separate Google Geocoding API key needed — keeps everything on the existing Apify token/budget).

**Done when:** all decisions recorded (above); ready to build.

---

## Phase 1 — Workstream E foundation: data model & schema (design first)

**Datastore = Google Sheets (decided). Tenancy = single-client (decided).** The staged + tagged model is built as extra Sheets tabs + record tags — no new database. The *schema* must support tags + stages now, or everything else needs a refactor later.

### 1A. New record-level tag fields (add to `schema.py` + `contractors` tab headers)
- [ ] `client_id` (default a single seeded client — single-client now, multi-client-ready later)
- [ ] `record_type` — `contractor` | `vendor`
- [ ] `state`, `county`, `city_tier` (city/zip already exist)
- [ ] `source` per record — `google_business` | `bbb` | `dbpr` | `tn_license` | `nashville_open_data` | `vendor_seed` | …
- [ ] `scrape_run_id` (= job_id) + `scraped_at` (exists)
- [ ] `canonical_entity_id` (entity-resolution key; upgrade of today's `dedupe_key`)
- [ ] status flags: `out_of_territory` (bool), `excluded_reason` (string, for lumber etc.), `enrichment_status`
- [ ] vendor flags (vendor records): `is_big_box` (bool) / `vendor_type` (`specialty_distributor` | `big_box_retailer` | `independent`)

### 1B. Stage separation (raw immutable → derived)
- [ ] Define logical stages: **raw → normalized → enriched → filtered/validated → deliverable**.
- [ ] Never mutate raw. Each stage reads previous, writes its own layer (new tabs/tables: `raw_records`, or staged columns + status).
- [ ] Reuse existing `stage_outputs` checkpoint pattern as a model.

### 1C. Reference tables (config ≠ scraped data)
- [ ] `territories` (state/region include-exclude)
- [ ] `city_tiers` (city + center coords + radius + tier)
- [ ] `vendor_aliases` (alias → canonical network)
- [ ] `negative_keywords` (lumber filter list)
- [ ] `dealer_accounts` (client's account locations: name, address, geocoded lat/lng) — anchors for the contractor 50-mi radius (additional req #3)
- [ ] Wire into `sheets_schema.py SCHEMA` (+ `db.py` accessors). Keep editable via UI.

### 1D. Access / export layer
- [ ] Idempotent upsert keyed on `(canonical_entity_id, source)`.
- [ ] Derived exports/views parameterized by `client_id`, `record_type`, `territory`, `tier` — apply territory + lumber + tier filters **at export time** (keep underlying data wide).
- [ ] Per-client isolation: single-client now, so just filter exports by `client_id` (no RLS/per-client schema needed yet — the field is there for future multi-client).
- [ ] Contact-data access control + retention policy.

**Done when:** same underlying dataset can produce a client-scoped, territory-scoped contractor list AND vendor list on demand; raw preserved; duplicates merged; every exclusion/source traceable.

### 1E. Per-source raw layer + staged provenance (Raasta B — keep merged AND source rows)
Keep the fast merged `contractors` row, BUT also satisfy the spec's "keep the source rows; don't overwrite them" + staged model — without 5 heavy stage-tabs.
- [ ] New `source_records` tab (mirrored): one **append-only, immutable** row per (business, source) — Google / BBB / license / Apollo / vendor-seed snapshot, with a `data` JSON blob of the full payload. Never overwritten = the **raw** layer.
- [ ] Foreign key: `canonical_entity_id` links each source row to its merged `contractors` row → "view this contractor's sources separately".
- [ ] `record_source(record, source, run_id, stage='raw')` — append a raw snapshot.
- [ ] Extend `upsert_contractor(..., source, run_id, stage)` — each scraper does TWO writes: (1) append raw row to `source_records`, (2) upsert merged row into `contractors`.
- [ ] Stage progression tracked as a `stage` field on the canonical row (`raw → normalized → enriched → filtered`); `deliverable` stays a derived view (1D). No per-stage tabs (too heavy for Sheets).
- [ ] `list_source_records(canonical_entity_id)` — fetch a business's per-source rows.

---

## Phase 2 — Workstream A: Geography & territory foundation

### 2A. Configurable geography (replace hardcoded)
- [ ] Extend `cities.yaml` + `cities`/`city_zips` tabs with: `state`, `county`, `region`, `tier`, `center_lat`, `center_lng`, `radius_miles`. FL rows keep defaults → **FL untouched**.
- [ ] Add **Tennessee** config alongside FL.

### 2B. Region include/exclude + Memphis hard exclusion
- [ ] `territory_exclusions` reference list (runtime-read, UI-editable).
- [ ] **Memphis metro** = Memphis, Bartlett, Germantown, Collierville + far-SW TN → never scraped or returned.
- [ ] Rest of TN (Knoxville, Chattanooga, Pigeon Forge) = in-territory.
- [ ] Helper `is_excluded(zip|city|county)` applied **before** scraping (never spend runs on excluded zips).

### 2C. Radii + geocoding + zip computation (new `agent/geography.py`)
- [ ] Two radii: **vendor = 20 mi**, **contractor = 50 mi** (independently configurable).
- [ ] Geocoding step: **dealer-account** address → coordinates via an **Apify paid geocoding actor** (decided — reuses the existing `APIFY_API_TOKEN`, no new API key/budget line).
- [ ] **Contractor pipeline:** from `dealer_accounts` locations (additional req #3, e.g. each Home Depot), compute all zips within the **50-mi** radius → dedupe → apply territory exclusion → feed scraper. (City tiers still set scrape priority/order.)
- [ ] **Vendor pipeline:** from prioritized city centers, **20-mi** radius (Phase 4).
- [ ] Need: zip→lat/lng dataset + haversine distance util. **Done DBPR-style** — `agent/zip_loader.py` fetches GeoNames US.zip **live on demand** (filtered to ZIP_STATES, in-memory cached per process), with a bundled `config/zip_coords.csv` snapshot as an offline fallback.

### 2D. City prioritization (key feature)
- [ ] **Tier 1 (named, no size filter):** Pigeon Forge, Nashville, Chattanooga, Jackson, Columbia, Knoxville.
- [ ] **Tier 2:** all other TN cities pop ≥ 50,000 — precomputed **static list** (city + center coords + radius).
- [ ] Run-order: Tier 1 scraped before Tier 2 (make `list_cities()` tier-aware; pipeline iterates by tier).
- [ ] Tier tag written on every record.

**Done when:** a run scoped to TN auto-skips Memphis, scrapes Tier 1 first, tags every record with city + tier + zip — all from editable config.

---

## Phase 3 — Workstream B: Contractor scraper (Tennessee)

- [ ] **Do not modify** existing keyword/ICP search logic — reuse `scraper_google.py` + `classifier.py` as-is.
- [ ] Feed it the TN in-territory zip set from Phase 2.
- [ ] New `agent/scraper_tn_license.py` (mirrors DBPR interface), sources in priority order:
  - [ ] **Nashville open data** "Registered Professional Contractors" (data.nashville.gov) — **PRIMARY, free, build now** (Phase 0 decision). Check Murfreesboro/Franklin/Knoxville/Chattanooga equivalents.
  - [ ] ~~**TDCI open-records request** baseline roster~~ — **DEFERRED** (optional, add later only if needed).
  - [ ] **verify.tn.gov / search.cloud.commerce.tn.gov** — verify-a-name only (enrichment, not discovery); optional.
- [ ] License = **validation/enrichment**, not discovery. Discovery stays Google + BBB + keywords.
- [ ] Pipeline Phase 5: branch by state → FL uses DBPR, TN uses `scraper_tn_license`.
- [ ] Filter TN license by **trade classification code**, not the word "drywall".
- [ ] Apply lumber exclusion (Phase 5/D).
- [ ] **Document (don't solve):** small sub-threshold crews absent from license data; license keyed by classification code.

**Done when:** a TN run returns contractor records scoped to in-territory zips, cross-referenced against available license data, lumber filtered out.

---

## Phase 4 — Workstream C: Vendor scraper (new mode)

- [ ] Build as a **separate mode** (not a contractor-scraper modification). `record_type=vendor`.
- [ ] Anchor searches to prioritized city list, **20-mi vendor radius** from each city center. (Big-box stores are NOT anchors.)
- [ ] Query set: drywall supply / gypsum / building materials distributors.
- [ ] **Vendor alias / subsidiary map** (`vendor_aliases` reference table):
  - L&W Supply ↔ ABC Supply / ABC Supply Interiors → one network.
  - FBM = Foundation Building Materials.
  - GMS = Gypsum Mgmt & Supply → local brands (Drywall Supply, Tucker Materials, Gator Gypsum, Rocky Top Materials) — **alias list mandatory**; all roll up to a **single "GMS" entity** in output (per Phase 0 decision).
  - Independents (Dealers Supply, Building Products Supply…) — capture by **category**, not fixed names.
- [ ] **Big-box retailers (Home Depot / Lowe's):** keep them, do NOT drop. Tag with `is_big_box = true` / `vendor_type = big_box_retailer` so export can include/exclude on demand. (Per Phase 0 decision — these chains own GMS/FBM, so the flag lets us reason about overlap without losing data.)
- [ ] Entity resolution merges multi-name networks → single `canonical_entity_id`.
- [ ] Use `Nashville_Drywall_Distributors.xlsx` as **seed/validation set** (confirm + enrich + discover new). Not final output.
- [ ] Output fields: distributor name + branch location + phone + notes (mirror seed sheet).
- [ ] Apply lumber exclusion (D) + Memphis exclusion.

**Done when:** a TN run produces a distributor list across prioritized cities, multi-name networks (esp. GMS) merged, validated against seed set.

---

## Phase 5 — Workstream D: Lumber exclusion (cross-cutting, into B & C)

- [ ] **Layer 1 — Category exclusion:** drop if Google Maps / BBB category = lumber / sawmill / lumberyard. (Use `GoogleSeed.google_categories`.)
- [ ] **Layer 2 — Negative-keyword list:** editable `negative_keywords` table (lumber, lumberyard, sawmill…) applied to name + description.
- [ ] **Layer 3 — Name-pattern matching:** clean category but lumber-signaling name → catch via regex.
- [ ] Apply all 3 layers to **both** contractor and vendor pipelines.
- [ ] **Flag, don't hard-delete:** set `excluded_reason`; keep the row (wide net + auditable). Filter happens at export.
- [ ] Hook into `classifier.py` (Layers 1-3) + new vendor filter; wire `excluded_reason` through `schema.py` + `contractors` tab.

**Done when:** known lumber businesses reliably absent from both deliverable lists; every exclusion recorded with a reason.

---

## Phase 6 — Integration, rebrand, UI, QA

### 6A. Rebrand → "Westpac Sales Scraper" (additional req #1)
- [ ] Update UI titles/headers/nav, README, page copy, browser tab title from "Contractor Scraper" → **"Westpac Sales Scraper"**. (Low-risk; can be pulled earlier if desired.)

### 6B. Mode + territory selection
- [ ] Pipeline: select mode (contractor | vendor) + territory (FL | TN) at job start (Dashboard).
- [ ] Manage `dealer_accounts` from the UI (used as contractor anchors).

### 6C. Results / export / reference editors
- [ ] Frontend: territory + record_type + tier filters on Results; export endpoints; reference-table editors (territories, city tiers, vendor aliases, negative keywords, dealer accounts).

### 6D. QA
- [ ] Regression: full FL contractor run must produce identical results to today (additive proof).
- [ ] New tests: TN territory exclusion (Memphis), tier ordering, dealer-account radius, lumber 3-layer, vendor alias roll-up, entity resolution, export isolation.

---

## Resource needs summary

**All decisions locked — no new paid services beyond the existing Apify token.**

| Need | Decision |
|---|---|
| Google Maps discovery / BBB | ✅ Apify (existing) |
| Email/owner enrichment | ✅ Apollo (existing, paid) |
| Datastore | ✅ **Google Sheets** (stay — no Supabase) |
| Tenancy | ✅ **Single-client** (`client_id` field kept for future) |
| **Geocoding** (address → lat/lng) | ✅ **Apify paid actor** (reuses existing `APIFY_API_TOKEN` — no new key) |
| **ZIP → coords dataset** + distance | Free static dataset (Census/GeoNames) bundled in repo + haversine util |
| TN license data | **Nashville open data only** (free); TDCI deferred |
| Read seed `.xlsx` | `openpyxl`/`pandas` Python lib (free) |

---

## Execution sequence (one small step at a time)

We walk these in order. After each: plain-English summary + test against `backend/.env`. Proceed only on "next".

- **P0** — Confirm decisions + local env/auth works (Sheets reachable, Apify/Apollo keys load).
- **P1a** — Add tag fields to `schema.py` + `contractors` headers (back-compatible).
- **P1b** — Reference tables in `sheets_schema.py` (`territories`, `city_tiers`, `vendor_aliases`, `negative_keywords`, `dealer_accounts`) + `db.py` accessors.
- **P1c** — Staged-layer model + idempotent upsert on `(canonical_entity_id, source)`.
- **P1d** — Derived export views (client/territory/record_type/tier).
- **P2a** — Extend `cities.yaml` + seeding with `county/region/tier/coords/radius`; add TN config.
- **P2b** — Territory exclusion (`is_excluded`) + Memphis metro list.
- **P2c** — `agent/geography.py`: Apify geocoder + zip dataset + haversine + radius→zips.
- **P2d** — City tiers (Tier1 named, Tier2 ≥50k static) + tier-ordered scraping + tier tag.
- **P3** — `scraper_tn_license.py` (Nashville open data) + state-branch in enrich phase.
- **P4** — Vendor mode: queries, alias roll-up, big-box flag, seed `.xlsx`, entity resolution.
- **P5** — Lumber 3-layer filter (category / negative-keyword / name-pattern) + `excluded_reason`.
- **P6a** — Rebrand to "Westpac Sales Scraper".
- **P6b/c** — Mode+territory selection, dealer-account UI, Results filters/export, ref editors.
- **P6d** — FL regression + new tests.
