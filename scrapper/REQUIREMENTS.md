# Third-Party API Credentials — Contractor Scraper Agent

> Ye doc batata hai kaun-kaun se third-party API services ke accounts banane hain, har ek ka signup link, free tier limits, aur kya copy karke save karna hai. Build start karne se pehle saare boxes tick off karo.

---

## 1. Outscraper ⭐ (PRIMARY — Google Maps + BBB scraping)

- **Why:** Bypasses Google Places API ka 60-result cap. Returns business emails bundled in same scrape. Supports BBB scraping too. Cheapest at scale (~$30 per 10,000 leads).
- **Signup:** https://outscraper.com → Sign up (Google OAuth ya email)
- **Free tier:** $5-25 free credits on signup
- **What to copy:** Profile menu → **"Profile and API Usage"** → **API Token**
- **Env var name:** `OUTSCRAPER_API_KEY`
- **Estimated paid cost:** ~$45-75 per full run (15-25k raw rows × ~$3 per 1,000)
- **BBB enrichment:** ~$5-15 per run via Outscraper BBB actor

**Checklist:**
- [ ] Signup done
- [ ] Email verified
- [ ] API token copied & saved
- [ ] Free credits visible in dashboard
- [ ] Billing method added (only when free credits run out)

---

## 2. Hunter.io (Email finder from website domain)

- **Why:** Cheapest way to find business emails when only website is known. Used for rows missing email after Outscraper.
- **Signup:** https://hunter.io → Sign up
- **Free tier:** **25 searches/month FREE FOREVER** (no card needed)
- **What to copy:** Dashboard → **API** tab → **API Key**
- **Env var name:** `HUNTER_API_KEY`
- **Paid plan (if needed):** $49/month for 500 searches

**Checklist:**
- [ ] Signup done
- [ ] Email verified
- [ ] API key copied & saved
- [ ] Free quota confirmed (25/month visible)

---

## 3. Apollo.io (Owner name + LinkedIn enrichment)

- **Why:** Best SMB construction industry coverage. Finds business owner names + LinkedIn URLs for personalized outbound.
- **Signup:** https://apollo.io → Sign up
- **Free tier:** Limited free plan credits + **14-day full trial** of paid plan
- **What to copy:** Settings → **Integrations** → **API** → **API Key**
- **Env var name:** `APOLLO_API_KEY`
- **Paid plan (if needed):** $49-99/month starter tier

**Checklist:**
- [ ] Signup done
- [ ] Email verified
- [ ] Workspace created
- [ ] API key copied & saved

---

## 4. People Data Labs (OPTIONAL — last-resort fallback)

- **Why:** Pay-as-you-go person enrichment when both Hunter.io AND Apollo.io miss. Strong final fallback.
- **Signup:** https://dashboard.peopledatalabs.com/signup
- **Free tier:** **100 free credits** on signup
- **What to copy:** Dashboard → **API Keys**
- **Env var name:** `PDL_API_KEY`
- **Paid cost:** $0.05-0.20 per successful match (pay-as-you-go)

**Checklist:**
- [ ] Signup done (optional for v1)
- [ ] API key copied & saved
- [ ] Free 100 credits visible

---

## 5. Apify (OPTIONAL — backup if Outscraper rejected)

- **Why:** Alternative scraping platform if Outscraper account gets restricted or rejected. Has equivalent Google Maps + BBB actors.
- **Signup:** https://apify.com → Sign up
- **Free tier:** $5/month free credits
- **What to copy:** Settings → **Integrations** → **API token**
- **Env var name:** `APIFY_API_TOKEN`

**Checklist:**
- [ ] Signup done (only if Outscraper fails or for redundancy)
- [ ] API token copied & saved

---

## Quick Reference Table

| # | Service | URL | Env Var | Free Tier | Priority |
|---|---|---|---|---|---|
| 1 | Outscraper | outscraper.com | `OUTSCRAPER_API_KEY` | $5-25 credits | **MUST** |
| 2 | Hunter.io | hunter.io | `HUNTER_API_KEY` | 25/mo forever | **MUST** |
| 3 | Apollo.io | apollo.io | `APOLLO_API_KEY` | Free + 14d trial | **MUST** |
| 4 | People Data Labs | peopledatalabs.com | `PDL_API_KEY` | 100 credits | Optional |
| 5 | Apify | apify.com | `APIFY_API_TOKEN` | $5/mo | Backup |

---

## NO Credentials Needed For

These data sources are accessed without any API key:

- **Florida DBPR** (myfloridalicense.com) — Public records under Florida Sunshine Law (Chapter 119, F.S.). Scraped via Playwright. No account.
- **Google Maps direct** — Outscraper handles all Google scraping, no Google Cloud account needed.
- **BBB (Better Business Bureau)** — Outscraper BBB actor handles it, no BBB account needed.

---
