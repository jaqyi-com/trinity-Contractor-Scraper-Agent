# api/routes/settings.py
# App settings — per-run final-record cap (max_final_records) + per-service USD
# cost budgets (discovery / BBB / Apollo). A budget of null means "unlimited".

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from agent.db import (
    get_max_final_records, set_setting, DEFAULT_MAX_FINAL_RECORDS,
    get_discovery_budget_usd, get_bbb_budget_usd, get_apollo_budget_usd,
    get_vendor_radius_miles, get_contractor_radius_miles,
    DEFAULT_VENDOR_RADIUS_MI, DEFAULT_CONTRACTOR_RADIUS_MI,
    get_enable_tn_verify,
)
from api.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])

# Upper bound — guards against a typo that would make a run scrape forever
# (and rack up enrichment cost). Raise if you genuinely need larger runs.
MAX_FINAL_RECORDS_CEILING = 100_000
# Sanity ceiling on a single-run budget — guards against a fat-finger ($50000).
MAX_BUDGET_USD = 10_000.0
# Sanity ceiling on a search radius (miles).
MAX_RADIUS_MI = 500.0


class SettingsResponse(BaseModel):
    max_final_records: int
    default_max_final_records: int = DEFAULT_MAX_FINAL_RECORDS
    # null = unlimited (no cap) for each.
    discovery_budget_usd: Optional[float] = None
    bbb_budget_usd: Optional[float] = None
    apollo_budget_usd: Optional[float] = None
    # TN search radii (miles) — vendor anchors on city centers, contractor on dealers.
    vendor_radius_miles: float = DEFAULT_VENDOR_RADIUS_MI
    contractor_radius_miles: float = DEFAULT_CONTRACTOR_RADIUS_MI
    # OPTIONAL statewide TN verify-a-name license enrichment. OFF by default — it's
    # a slow per-name lookup (no bulk/public API) that can add minutes to a TN run.
    enable_tn_verify: bool = False


class UpdateSettingsBody(BaseModel):
    max_final_records: int = Field(ge=1, le=MAX_FINAL_RECORDS_CEILING)
    # Omit a field or send null to leave a service UNLIMITED. Send a positive
    # number to cap that service's spend for the next run.
    discovery_budget_usd: Optional[float] = Field(default=None, gt=0, le=MAX_BUDGET_USD)
    bbb_budget_usd: Optional[float] = Field(default=None, gt=0, le=MAX_BUDGET_USD)
    apollo_budget_usd: Optional[float] = Field(default=None, gt=0, le=MAX_BUDGET_USD)
    vendor_radius_miles: Optional[float] = Field(default=None, gt=0, le=MAX_RADIUS_MI)
    contractor_radius_miles: Optional[float] = Field(default=None, gt=0, le=MAX_RADIUS_MI)
    # None = leave unchanged; true/false = set the statewide-verify toggle.
    enable_tn_verify: Optional[bool] = None


def _current() -> SettingsResponse:
    return SettingsResponse(
        max_final_records=get_max_final_records(),
        discovery_budget_usd=get_discovery_budget_usd(),
        bbb_budget_usd=get_bbb_budget_usd(),
        apollo_budget_usd=get_apollo_budget_usd(),
        vendor_radius_miles=get_vendor_radius_miles(),
        contractor_radius_miles=get_contractor_radius_miles(),
        enable_tn_verify=get_enable_tn_verify(),
    )


@router.get("", response_model=SettingsResponse)
async def get_settings():
    """Current pipeline settings (used by the Dashboard run config)."""
    return _current()


@router.put("", response_model=SettingsResponse)
async def update_settings(body: UpdateSettingsBody):
    """Update the per-run cap + cost budgets. Applies to the NEXT pipeline run.
    A null budget stores the literal "none" → the pipeline treats it as unlimited."""
    if body.max_final_records < 1 or body.max_final_records > MAX_FINAL_RECORDS_CEILING:
        raise HTTPException(status_code=422, detail="max_final_records out of range")
    set_setting("max_final_records", str(body.max_final_records))
    # None → store "none" (unlimited); a number → store as-is.
    set_setting("discovery_budget_usd", "none" if body.discovery_budget_usd is None else str(body.discovery_budget_usd))
    set_setting("bbb_budget_usd", "none" if body.bbb_budget_usd is None else str(body.bbb_budget_usd))
    set_setting("apollo_budget_usd", "none" if body.apollo_budget_usd is None else str(body.apollo_budget_usd))
    # Radii: only overwrite when a value is sent (None = leave unchanged).
    if body.vendor_radius_miles is not None:
        set_setting("vendor_radius_miles", str(body.vendor_radius_miles))
    if body.contractor_radius_miles is not None:
        set_setting("contractor_radius_miles", str(body.contractor_radius_miles))
    # Toggle (None = leave unchanged) — store canonical "true"/"false".
    if body.enable_tn_verify is not None:
        set_setting("enable_tn_verify", "true" if body.enable_tn_verify else "false")
    return _current()
