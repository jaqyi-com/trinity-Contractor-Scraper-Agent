# schema.py
# All Pydantic data contracts in a single file (production-scraper pattern).
# Stages pass these models to each other.

from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel


# ──────────────────────────────────────────────────────────────
# Discovery — what the Apify Google Maps actor returns per business
# ──────────────────────────────────────────────────────────────
class GoogleSeed(BaseModel):
    place_id: str
    business_name: str
    city: str
    zip_code: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    google_categories: List[str] = []
    services_listed: List[str] = []
    description: Optional[str] = ""
    google_rating: Optional[float] = None
    google_review_count: Optional[int] = None
    social_profiles: Dict[str, str] = {}
    raw: Dict[str, Any] = {}  # full discovery payload (Apify Maps) for audit


# ──────────────────────────────────────────────────────────────
# DBPR license record
# ──────────────────────────────────────────────────────────────
class DBPRLicense(BaseModel):
    license_number: str
    license_category: str  # e.g. "Gypsum Drywall Contractor", "CGC"
    licensee_name: str
    dba_name: Optional[str] = None
    status: str  # "Current/Active" | "Inactive" | "Delinquent" | "Null and Void"
    city: Optional[str] = None
    zip_code: Optional[str] = None
    phone: Optional[str] = None
    original_issue_date: Optional[str] = None
    raw: Dict[str, Any] = {}


# ──────────────────────────────────────────────────────────────
# Tier classification decision (audit log entry)
# ──────────────────────────────────────────────────────────────
class MatchedKeyword(BaseModel):
    tier: str       # 'TIER_1_DRYWALL', 'EXCLUDE_HARD', etc.
    keyword: str


class ClassificationDecision(BaseModel):
    decision: str   # 'INCLUDED' | 'EXCLUDED'
    assigned_tier: Optional[str] = None  # e.g. 'TIER_1_DRYWALL'
    matched_keywords: List[MatchedKeyword] = []
    exclusion_keywords: List[MatchedKeyword] = []
    classifier_text: str = ""
    reason: str = ""


# ──────────────────────────────────────────────────────────────
# BBB enrichment result
# ──────────────────────────────────────────────────────────────
class BBBEnrichment(BaseModel):
    bbb_id: Optional[str] = None
    rating: Optional[str] = None        # 'A+', 'A', 'B', etc.
    accredited: bool = False
    years_in_business: Optional[int] = None
    out_of_business: bool = False


# ──────────────────────────────────────────────────────────────
# Email enrichment result
# ──────────────────────────────────────────────────────────────
class EmailEnrichment(BaseModel):
    email: Optional[str] = None
    owner_name: Optional[str] = None
    linkedin_url: Optional[str] = None
    sources: List[str] = []   # ['google', 'apollo', 'dbpr', 'bbb']


# ──────────────────────────────────────────────────────────────
# Final master row — matches PDF Section 5 output schema
# ──────────────────────────────────────────────────────────────
class ContractorRow(BaseModel):
    business_name: str
    city: Optional[str] = None
    zip_code: Optional[str] = None
    address: Optional[str] = None

    tier: Optional[str] = None
    specialty_keywords: List[str] = []
    google_categories: List[str] = []
    services_listed: List[str] = []

    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    owner_name: Optional[str] = None

    license_status: str = "unknown"
    license_numbers: List[str] = []
    license_categories: List[str] = []

    google_rating: Optional[float] = None
    google_review_count: Optional[int] = None

    bbb_rating: Optional[str] = None
    bbb_accredited: Optional[bool] = None
    years_in_business: Optional[int] = None

    social_profiles: Dict[str, str] = {}
    sources: List[str] = []
    place_ids: List[str] = []

    scraped_at: Optional[datetime] = None
    job_id: Optional[str] = None


# ──────────────────────────────────────────────────────────────
# Keyword (DB-managed, used by classifier + Keywords UI tab)
# ──────────────────────────────────────────────────────────────
class Keyword(BaseModel):
    id: Optional[int] = None
    tier: str  # 'TIER_1_DRYWALL' | 'EXCLUDE_HARD' | etc.
    keyword: str
    active: bool = True
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    created_by: Optional[str] = "system"


# ──────────────────────────────────────────────────────────────
# Job tracking — for /api/jobs/{id}/status frontend polling
# ──────────────────────────────────────────────────────────────
class StageProgress(BaseModel):
    status: str = "pending"  # 'pending' | 'running' | 'done' | 'failed'
    rows_in: int = 0
    rows_out: int = 0
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class JobSummary(BaseModel):
    job_id: str
    status: str  # 'pending' | 'running' | 'completed' | 'failed' | 'interrupted'
    current_stage: Optional[str] = None
    stages_progress: Dict[str, StageProgress] = {}
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
