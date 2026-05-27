# api/routes/cities.py
# Cities + ZIP CRUD endpoints.
# All require JWT (router-level dependency).

from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from agent.db import (
    list_cities,
    get_city,
    create_city,
    update_city,
    delete_city,
    add_zip,
    remove_zip,
)
from api.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])


class CreateCityBody(BaseModel):
    name: str = Field(min_length=1)
    state: str = Field(default="FL", min_length=2, max_length=2)
    zips: Optional[List[str]] = None


class UpdateCityBody(BaseModel):
    name: Optional[str] = None
    state: Optional[str] = None


class ZipBody(BaseModel):
    zip_code: str = Field(min_length=3, max_length=10)


@router.get("")
async def list_endpoint():
    return list_cities()


@router.get("/{city_id}")
async def get_endpoint(city_id: int):
    city = get_city(city_id)
    if not city:
        raise HTTPException(status_code=404, detail="City not found")
    return city


@router.post("")
async def create_endpoint(body: CreateCityBody):
    created = create_city(body.name.strip(), body.state.upper(), body.zips or [])
    if not created:
        raise HTTPException(status_code=409, detail="City with this name+state already exists")
    return created


@router.put("/{city_id}")
async def update_endpoint(city_id: int, body: UpdateCityBody):
    updated = update_city(
        city_id,
        name=body.name.strip() if body.name else None,
        state=body.state.upper() if body.state else None,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="City not found")
    return updated


@router.delete("/{city_id}")
async def delete_endpoint(city_id: int):
    ok = delete_city(city_id)
    if not ok:
        raise HTTPException(status_code=404, detail="City not found")
    return {"deleted": city_id}


@router.post("/{city_id}/zips")
async def add_zip_endpoint(city_id: int, body: ZipBody):
    ok = add_zip(city_id, body.zip_code)
    if not ok:
        # Could be city missing OR duplicate zip — disambiguate
        if not get_city(city_id):
            raise HTTPException(status_code=404, detail="City not found")
        raise HTTPException(status_code=409, detail="ZIP already exists on this city")
    return get_city(city_id)


@router.delete("/{city_id}/zips/{zip_code}")
async def remove_zip_endpoint(city_id: int, zip_code: str):
    ok = remove_zip(city_id, zip_code)
    if not ok:
        raise HTTPException(status_code=404, detail="ZIP not found on this city")
    return get_city(city_id)
