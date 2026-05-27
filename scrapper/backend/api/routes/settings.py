# api/routes/settings.py
# App settings — currently just the per-run final-record cap (max_final_records).

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from agent.db import get_max_final_records, set_setting, DEFAULT_MAX_FINAL_RECORDS
from api.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])

# Upper bound — guards against a typo that would make a run scrape forever
# (and rack up enrichment cost). Raise if you genuinely need larger runs.
MAX_FINAL_RECORDS_CEILING = 100_000


class SettingsResponse(BaseModel):
    max_final_records: int
    default_max_final_records: int = DEFAULT_MAX_FINAL_RECORDS


class UpdateSettingsBody(BaseModel):
    max_final_records: int = Field(ge=1, le=MAX_FINAL_RECORDS_CEILING)


@router.get("", response_model=SettingsResponse)
async def get_settings():
    """Current pipeline settings (used by the Dashboard run config)."""
    return SettingsResponse(max_final_records=get_max_final_records())


@router.put("", response_model=SettingsResponse)
async def update_settings(body: UpdateSettingsBody):
    """Update the per-run final-record cap. Applies to the NEXT pipeline run."""
    if body.max_final_records < 1 or body.max_final_records > MAX_FINAL_RECORDS_CEILING:
        raise HTTPException(status_code=422, detail="max_final_records out of range")
    set_setting("max_final_records", str(body.max_final_records))
    return SettingsResponse(max_final_records=get_max_final_records())
