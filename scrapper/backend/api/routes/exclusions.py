# api/routes/exclusions.py
# Territory-exclusion list endpoints. Locked base rules (Memphis metro) are
# read-only; users ADD more cities to exclude (chosen from the cities dropdown),
# never free text. All require JWT (router-level dependency).

from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from agent.db import list_exclusions, add_city_exclusion, delete_exclusion
from api.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])


class AddExclusionBody(BaseModel):
    city: str
    state: Optional[str] = "TN"


@router.get("")
async def list_endpoint(state: Optional[str] = None):
    """All active exclusions (locked base + user-added)."""
    return list_exclusions(state)


@router.post("")
async def add_endpoint(body: AddExclusionBody):
    """Exclude a city (picked from the cities dropdown) → resolves to its ZIPs."""
    if not body.city or not body.city.strip():
        raise HTTPException(status_code=422, detail="city is required")
    return add_city_exclusion(body.city.strip(), (body.state or "TN").upper())


@router.delete("/{rule_id}")
async def delete_endpoint(rule_id: int):
    """Delete a user-added exclusion. Locked base rules (Memphis) are protected."""
    try:
        ok = delete_exclusion(rule_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="exclusion not found")
    return {"deleted": True, "id": rule_id}
