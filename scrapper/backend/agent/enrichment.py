# enrichment.py
# Email + company enrichment — PDF Section 4.
# Stack: Apollo (paid) only. Order: discovery-bundled email (Apify Maps, stage1)
# → Apollo People Search (owner email + name + LinkedIn).
# Company facts (founded year, phone, company LinkedIn) come from apollo_company.

import os
import requests
from dotenv import load_dotenv

from agent.schema import ContractorRow, EmailEnrichment
from utils.url_normalizer import extract_domain

load_dotenv()

APOLLO_API_KEY = os.getenv("APOLLO_API_KEY")

HTTP_TIMEOUT = 20

# Domains that aren't a business's own site — enriching these returns garbage
# (e.g. a facebook.com "website" makes Apollo return Meta employees).
_NON_BUSINESS_DOMAINS = {
    "facebook.com", "fb.com", "m.facebook.com", "instagram.com", "linkedin.com",
    "twitter.com", "x.com", "youtube.com", "google.com", "sites.google.com",
    "business.site", "ueni.com", "ueniweb.com", "wix.com", "wixsite.com",
    "godaddysites.com", "wordpress.com", "blogspot.com", "yelp.com", "bbb.org",
}


def _enrichable_domain(domain: str | None) -> str | None:
    """Return the domain only if it's plausibly the business's own site."""
    if not domain:
        return None
    d = domain.lower()
    if d in _NON_BUSINESS_DOMAINS or any(d.endswith("." + b) for b in _NON_BUSINESS_DOMAINS):
        return None
    return domain


_LEADER_TITLES = ("owner", "president", "ceo", "founder", "principal", "partner", "vice president", "vp", "manager")


def _apollo_person_email(domain: str) -> EmailEnrichment:
    """
    Two-step Apollo flow (the search endpoint masks contact data):
    1. api_search by company domain → candidate people (id + has_email).
    2. people/match on the best candidate with reveal → actual work email,
       name, LinkedIn. A paid Apollo key + credits reveals the email.
    """
    domain = _enrichable_domain(domain)
    if not APOLLO_API_KEY or not domain:
        return EmailEnrichment()

    headers = {"Content-Type": "application/json", "X-Api-Key": APOLLO_API_KEY}

    # Step 1 — search people at the domain.
    try:
        resp = requests.post(
            "https://api.apollo.io/api/v1/mixed_people/api_search",
            headers=headers,
            json={"q_organization_domains_list": [domain], "page": 1, "per_page": 10},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        people = resp.json().get("people") or []
    except Exception as e:
        print(f"⚠️  Apollo search error for {domain}: {e}")
        return EmailEnrichment()

    if not people:
        return EmailEnrichment()

    # Prefer someone with an email on file, then a leadership-ish title.
    def rank(p: dict) -> tuple:
        title = (p.get("title") or "").lower()
        return (bool(p.get("has_email")), any(t in title for t in _LEADER_TITLES))

    best = sorted(people, key=rank, reverse=True)[0]
    pid = best.get("id")
    if not pid:
        return EmailEnrichment()

    # Step 2 — reveal the contact via people/match.
    try:
        resp = requests.post(
            "https://api.apollo.io/api/v1/people/match",
            headers=headers,
            params={"id": pid, "reveal_personal_emails": "true"},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        person = resp.json().get("person") or {}
    except Exception as e:
        print(f"⚠️  Apollo match error for {domain}: {e}")
        return EmailEnrichment()

    email = person.get("email")
    if email and "not_unlocked" in email:
        email = None
    return EmailEnrichment(
        email=email,
        owner_name=person.get("name"),
        linkedin_url=person.get("linkedin_url"),
        sources=["apollo"],
    )


def apollo_company(domain: str) -> dict:
    """
    Company-level facts from Apollo org enrich — feeds non-email fields:
    founded_year → years_in_business, plus phone + company LinkedIn. {} on miss.
    """
    domain = _enrichable_domain(domain)
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


def enrich_email(row: ContractorRow) -> EmailEnrichment:
    """
    Email/owner cascade:
    1. Keep the discovery-bundled email if present (Apify Maps, stage1).
    2. Apollo People Search for a decision-maker's email + name + LinkedIn.
    """
    if row.email:
        return EmailEnrichment(email=row.email, sources=["google"])

    domain = extract_domain(row.website) if row.website else None
    if not domain:
        return EmailEnrichment()

    return _apollo_person_email(domain)
