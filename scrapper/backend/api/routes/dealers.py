# api/routes/dealers.py
# Dealer/vendor ACCOUNT locations (the client's accounts) — these anchor the TN
# contractor 50-mile radius (spec additional req #3). CRUD over the editable
# `dealer_accounts` reference table. On create/update we geocode the address →
# (lat, lng) when coords aren't supplied, so targeting can compute the radius.
# All require JWT (router-level dependency).

from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from agent.db import list_ref, create_ref, update_ref, delete_ref
from api.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])

TAB = "dealer_accounts"


class DealerBody(BaseModel):
    name: str
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = "TN"
    zip_code: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    radius_miles: Optional[float] = None      # blank → use the global contractor radius
    is_big_box: Optional[bool] = False        # e.g. a Home Depot account
    client_id: Optional[str] = None
    notes: Optional[str] = None
    active: Optional[bool] = True


def _geocode_if_needed(fields: dict) -> dict:
    """Fill (lat, lng) from the address when not supplied. Best-effort — geocoding
    failure leaves coords blank (the account still saves; targeting just can't use
    it for a radius until coords are added)."""
    if fields.get("lat") is not None and fields.get("lng") is not None:
        return fields
    addr = fields.get("address") or " ".join(
        str(fields.get(k) or "") for k in ("city", "state", "zip_code")
    ).strip()
    if not addr:
        return fields
    try:
        from agent.geography import geocode_address
        coords = geocode_address(addr)
    except Exception as e:                     # never block a save on geocoding
        print(f"⚠️  [dealers] geocode failed for {addr!r}: {e}")
        coords = None
    if coords:
        fields["lat"], fields["lng"] = coords[0], coords[1]
    return fields


@router.get("")
async def list_endpoint():
    """All dealer/vendor accounts (active and inactive) for the editor."""
    return list_ref(TAB)


@router.post("")
async def add_endpoint(body: DealerBody):
    if not body.name or not body.name.strip():
        raise HTTPException(status_code=422, detail="name is required")
    fields = body.model_dump()
    fields["name"] = fields["name"].strip()
    if fields.get("state"):
        fields["state"] = fields["state"].upper()
    return create_ref(TAB, _geocode_if_needed(fields))


@router.put("/{row_id}")
async def update_endpoint(row_id: int, body: DealerBody):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if "name" in fields:
        fields["name"] = fields["name"].strip()
    if fields.get("state"):
        fields["state"] = fields["state"].upper()
    # Re-geocode only if the caller cleared coords but gave a location.
    fields = _geocode_if_needed(fields)
    row = update_ref(TAB, row_id, fields)
    if not row:
        raise HTTPException(status_code=404, detail="dealer account not found")
    return row


@router.delete("/{row_id}")
async def delete_endpoint(row_id: int):
    if not delete_ref(TAB, row_id):
        raise HTTPException(status_code=404, detail="dealer account not found")
    return {"deleted": True, "id": row_id}
