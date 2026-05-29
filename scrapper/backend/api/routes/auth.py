# api/routes/auth.py
# Auth endpoints — login, identity.

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from api.auth import (
    verify_password,
    create_access_token,
    get_current_user,
)
from agent.db import get_user_by_email

router = APIRouter()


class LoginBody(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginBody):
    """Validate credentials, return JWT."""
    # 🔎 DIAG — prints land in Cloud Run logs. Strip these once login works.
    print(f"🔎 [login] attempt for email={body.email!r}")
    from agent.sheets_client import get_db
    db = get_db()
    print(f"🔎 [login] users mirror size = {db.count('users')}")

    user = get_user_by_email(body.email)
    if not user:
        print(f"❌ [login] no user row for {body.email!r}")
        # Show a few sample emails so we can tell if seed ran / which sheet we're on
        sample = [r.get("email") for r in db.all_rows("users")[:5]]
        print(f"🔎 [login] sample emails in users tab: {sample}")
        raise HTTPException(status_code=401, detail="Invalid email or password")

    print(f"🔎 [login] user found: id={user.get('id')} email={user.get('email')!r}")
    if not verify_password(body.password, user["password_hash"]):
        print(f"❌ [login] password mismatch for {body.email!r}")
        raise HTTPException(status_code=401, detail="Invalid email or password")

    print(f"✅ [login] success for {body.email!r}")
    token = create_access_token(
        {"sub": user["email"], "name": user["name"], "user_id": user["id"]}
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user["id"], "email": user["email"], "name": user["name"]},
    }


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    """Return the current user from JWT — used by frontend to validate token on mount."""
    return user