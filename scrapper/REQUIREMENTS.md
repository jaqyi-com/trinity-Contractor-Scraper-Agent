# Third-Party API Credentials — Contractor Scraper Agent

> Production stack needs only **two** provider keys (plus the Neon database).
> Discovery + license + BBB all run through Apify actors; enrichment runs through Apollo.

---

## 1. Apify ⭐ (PRIMARY — Google Maps discovery + DBPR + BBB)

- **Why:** One platform, three jobs via actors:
  - `compass/crawler-google-places` — Google Maps business discovery (name, phone, website, rating, categories; `scrapeContacts` also pulls website emails + socials)
  - `ws_tony/dbpr-florida-license-verification` — DBPR license fallback (for names not in the free bulk CSV)
  - `alizarin_refrigerator-owner/bbb-scraper` — BBB rating / accreditation
- **Signup:** https://apify.com → Sign up
- **Free tier:** $5/month free credits (enough for ~10-business test runs)
- **What to copy:** Settings → **Integrations** → **API token**
- **Env var:** `APIFY_API_TOKEN`
- **Paid cost:** ~$50–75 per full 6-metro run (discovery + BBB are the main cost)

**Checklist:**
- [ ] Signup done
- [ ] API token copied & saved
- [ ] Billing added (for a full run — $5 free credit only covers small tests)

---

## 2. Apollo.io (Email + owner + company enrichment)

- **Why:** Replaces email/owner enrichment. Two-step flow: People Search by
  company domain → People Match (reveal) returns owner work email + name + LinkedIn.
  Also provides company data (founded year → years_in_business, company LinkedIn).
- **Signup:** https://apollo.io → Sign up
- **What to copy:** Settings → **Integrations** → **API** → **API Key**
- **Env var:** `APOLLO_API_KEY`
- **⚠️ Must be a PAID key** — the free tier masks contact emails
  (`email_not_unlocked@...`). Paid reveals the real email.
- **Paid plan:** $49–99/month starter tier

**Checklist:**
- [ ] Signup done
- [ ] **Paid plan active** (free tier won't reveal emails)
- [ ] API key copied & saved

---

## Quick Reference Table

| # | Service | URL | Env Var | Role |
|---|---|---|---|---|
| 1 | Apify | apify.com | `APIFY_API_TOKEN` | **Discovery + DBPR + BBB** |
| 2 | Apollo.io | apollo.io | `APOLLO_API_KEY` | **Email + owner + company enrichment** |
| — | Neon Postgres | neon.tech | `POSTGRES_DSN` | Database (already provisioned) |

---

## NO Credentials Needed For

- **Florida DBPR** (myfloridalicense.com) — primary license source is the free,
  official bulk CSV (`CONSTRUCTIONLICENSE_1.csv`, which DBPR republishes weekly),
  refreshed at the start of every pipeline run by `agent/dbpr_loader.py`. No key,
  no browser. Apify DBPR actor is only a fallback for records the bulk file omits
  (Null & Void / delinquent).
- **Google Maps** — accessed via the Apify Maps actor; no Google Cloud account.
- **BBB** — Apify BBB actor; no BBB account.

> Removed from the original plan: Outscraper, Hunter.io, People Data Labs.
> Their roles are covered by Apify (discovery + website-scraped emails) and
> Apollo (owner email/name/LinkedIn).
