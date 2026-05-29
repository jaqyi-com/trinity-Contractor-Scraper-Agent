# api/routes/keywords.py
# Keywords CRUD endpoints — feeds Tab 2 of UI.

from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from agent.keywords import (
    list_keywords as _list,
    create_keyword,
    update_keyword,
    delete_keyword,
    list_changes,
)
from agent import db
from api.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])


class CreateBody(BaseModel):
    tier: str
    keyword: str
    notes: Optional[str] = None
    reason: Optional[str] = None
    created_by: Optional[str] = "user"


class UpdateBody(BaseModel):
    keyword: Optional[str] = None
    active: Optional[bool] = None
    notes: Optional[str] = None
    reason: Optional[str] = None
    changed_by: Optional[str] = "user"


class DeleteBody(BaseModel):
    reason: Optional[str] = None
    changed_by: Optional[str] = "user"


@router.get("")
async def list_endpoint(
    tier: Optional[str] = None,
    search: Optional[str] = None,
    active: Optional[bool] = None,
):
    rows = _list(tier)
    if search:
        s = search.lower()
        rows = [r for r in rows if s in (r.get("keyword") or "").lower() or s in (r.get("notes") or "").lower()]
    if active is not None:
        rows = [r for r in rows if bool(r.get("active")) == active]
    return rows


@router.get("/facets")
async def facets_endpoint():
    """Counts per tier — used by tier-tab badges."""
    return db.keyword_facets()


@router.get("/{keyword_id}")
async def get_endpoint(keyword_id: int):
    row = db.get_keyword(keyword_id)
    if not row:
        raise HTTPException(status_code=404, detail="Keyword not found")
    return row


@router.post("")
async def create_endpoint(body: CreateBody):
    created = create_keyword(
        tier=body.tier,
        keyword=body.keyword,
        notes=body.notes,
        created_by=body.created_by or "user",
        reason=body.reason,
    )
    if not created:
        raise HTTPException(status_code=409, detail="Keyword already exists for this tier")
    return created


@router.put("/{keyword_id}")
async def update_endpoint(keyword_id: int, body: UpdateBody):
    updates = {k: v for k, v in body.model_dump().items()
               if k in {"keyword", "active", "notes"} and v is not None}
    updated = update_keyword(
        keyword_id=keyword_id,
        updates=updates,
        changed_by=body.changed_by or "user",
        reason=body.reason,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Keyword not found")
    return updated


@router.delete("/{keyword_id}")
async def delete_endpoint(keyword_id: int, body: DeleteBody):
    ok = delete_keyword(
        keyword_id=keyword_id,
        changed_by=body.changed_by or "user",
        reason=body.reason,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Keyword not found")
    return {"deleted": keyword_id}


@router.get("/{keyword_id}/history")
async def history_endpoint(keyword_id: int):
    return list_changes(keyword_id)
