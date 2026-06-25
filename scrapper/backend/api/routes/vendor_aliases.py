# api/routes/vendor_aliases.py
# Vendor alias / subsidiary map (Workstream C) — rolls branch/brand names up to a
# single canonical network so e.g. all GMS subsidiaries (Tucker Materials, Gator
# Gypsum, Rocky Top Materials, …) and L&W ↔ ABC Supply merge into one entity.
# CRUD over the editable `vendor_aliases` reference table. All require JWT.

from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from agent.db import list_ref, create_ref, update_ref, delete_ref
from api.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])

TAB = "vendor_aliases"
# Mirrors vendor flags elsewhere; free text is allowed but these are the common values.
VENDOR_TYPES = {"specialty_distributor", "big_box_retailer", "independent"}


class AliasBody(BaseModel):
    alias: str                                  # the brand/branch name as it appears
    canonical_network: str                      # what it rolls up to (e.g. "GMS")
    entity: Optional[str] = None                # legal entity (e.g. "Gypsum Management & Supply")
    vendor_type: Optional[str] = "specialty_distributor"
    notes: Optional[str] = None
    active: Optional[bool] = True


@router.get("")
async def list_endpoint():
    """All alias rows (active + inactive) for the editor, sorted by network."""
    rows = list_ref(TAB)
    rows.sort(key=lambda r: ((r.get("canonical_network") or "").lower(), (r.get("alias") or "").lower()))
    return rows


@router.post("")
async def add_endpoint(body: AliasBody):
    if not body.alias.strip() or not body.canonical_network.strip():
        raise HTTPException(status_code=422, detail="alias and canonical_network are required")
    fields = body.model_dump()
    fields["alias"] = fields["alias"].strip()
    fields["canonical_network"] = fields["canonical_network"].strip()
    return create_ref(TAB, fields)


@router.put("/{row_id}")
async def update_endpoint(row_id: int, body: AliasBody):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    for k in ("alias", "canonical_network"):
        if k in fields:
            fields[k] = fields[k].strip()
    row = update_ref(TAB, row_id, fields)
    if not row:
        raise HTTPException(status_code=404, detail="alias not found")
    return row


@router.delete("/{row_id}")
async def delete_endpoint(row_id: int):
    if not delete_ref(TAB, row_id):
        raise HTTPException(status_code=404, detail="alias not found")
    return {"deleted": True, "id": row_id}
