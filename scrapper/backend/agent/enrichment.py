# enrichment.py
# Email + company enrichment — PDF Section 4.
# Order: Outscraper bundled (free, stage1) → Hunter → Apollo → PDL fallback.

import os
import requests
from dotenv import load_dotenv

from agent.schema import ContractorRow, EmailEnrichment
from utils.url_normalizer import extract_domain

load_dotenv()

HUNTER_API_KEY = os.getenv("HUNTER_API_KEY")
APOLLO_API_KEY = os.getenv("APOLLO_API_KEY")
PDL_API_KEY = os.getenv("PDL_API_KEY")

BUDGET_PER_ROW = 0.30  # PDF Section 4 cap
HTTP_TIMEOUT = 20


def _hunter_email_from_domain(domain: str) -> EmailEnrichment:
    """
    Hunter.io domain-search: return the highest-confidence email for a domain,
    using its first/last name as the owner contact.
    """
    if not HUNTER_API_KEY or not domain:
        return EmailEnrichment()

    try:
        resp = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={"domain": domain, "limit": 10, "api_key": HUNTER_API_KEY},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        emails = (resp.json().get("data") or {}).get("emails") or []
    except Exception as e:
        print(f"⚠️  Hunter error for {domain}: {e}")
        return EmailEnrichment()

    if not emails:
        return EmailEnrichment()

    # Prefer a decision-maker, else highest confidence.
    def rank(e: dict) -> tuple:
        pos = (e.get("position") or "").lower()
        is_leader = any(t in pos for t in ("owner", "president", "ceo", "founder", "principal", "vice president"))
        return (is_leader, e.get("confidence") or 0)

    best = sorted(emails, key=rank, reverse=True)[0]
    owner = " ".join(p for p in [best.get("first_name"), best.get("last_name")] if p) or None

    return EmailEnrichment(
        email=best.get("value"),
        owner_name=owner,
        linkedin_url=best.get("linkedin"),
        sources=["hunter"],
    )


def _apollo_enrich(business_name: str, domain: str) -> EmailEnrichment:
    """
    Apollo.io organization enrich. Free tier returns company-level data
    (linkedin, phone, founded year) but masks person emails, so we use it
    mainly for owner/linkedin context — not the email itself.
    """
    if not APOLLO_API_KEY or not domain:
        return EmailEnrichment()

    try:
        resp = requests.post(
            "https://api.apollo.io/v1/organizations/enrich",
            params={"domain": domain},
            headers={"Content-Type": "application/json", "X-Api-Key": APOLLO_API_KEY},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        org = resp.json().get("organization") or {}
    except Exception as e:
        print(f"⚠️  Apollo error for {domain}: {e}")
        return EmailEnrichment()

    if not org:
        return EmailEnrichment()

    return EmailEnrichment(
        owner_name=None,  # free tier masks contact emails/names
        linkedin_url=org.get("linkedin_url"),
        sources=["apollo"],
    )


def apollo_company(domain: str) -> dict:
    """
    Company-level facts from Apollo org enrich — feeds non-email fields:
    founded_year → years_in_business, plus phone + company linkedin.
    Returns {} on miss.
    """
    if not APOLLO_API_KEY or not domain:
        return {}

    try:
        resp = requests.post(
            "https://api.apollo.io/v1/organizations/enrich",
            params={"domain": domain},
            headers={"Content-Type": "application/json", "X-Api-Key": APOLLO_API_KEY},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        org = resp.json().get("organization") or {}
    except Exception as e:
        print(f"⚠️  Apollo company error for {domain}: {e}")
        return {}

    if not org:
        return {}

    out: dict = {}
    founded = org.get("founded_year")
    if founded:
        from datetime import datetime
        out["years_in_business"] = max(0, datetime.utcnow().year - int(founded))
    if org.get("phone"):
        out["phone"] = org.get("phone")
    if org.get("linkedin_url"):
        out["linkedin_url"] = org.get("linkedin_url")
    out["name"] = org.get("name")
    return out


def _pdl_enrich(business_name: str, domain: str) -> EmailEnrichment:
    """PDL company enrichment — last-resort fallback (no key configured = no-op)."""
    if not PDL_API_KEY:
        return EmailEnrichment()
    return EmailEnrichment()


def enrich_email(row: ContractorRow) -> EmailEnrichment:
    """
    Cascade per PDF 4:
    1. Keep Outscraper-bundled email if present (stage1).
    2. Hunter.io domain-search.
    3. Apollo.io for owner/linkedin context.
    4. PDL last-resort.
    """
    if row.email:
        return EmailEnrichment(email=row.email, sources=["outscraper"])

    domain = extract_domain(row.website) if row.website else None
    if not domain:
        return EmailEnrichment()

    hunter = _hunter_email_from_domain(domain)
    if hunter.email:
        # Backfill owner/linkedin from Apollo if Hunter didn't supply them.
        if not hunter.linkedin_url:
            apollo = _apollo_enrich(row.business_name, domain)
            if apollo.linkedin_url:
                hunter.linkedin_url = apollo.linkedin_url
                hunter.sources = list({*hunter.sources, *apollo.sources})
        return hunter

    apollo = _apollo_enrich(row.business_name, domain)
    if apollo.email or apollo.owner_name or apollo.linkedin_url:
        return apollo

    return _pdl_enrich(row.business_name, domain)
