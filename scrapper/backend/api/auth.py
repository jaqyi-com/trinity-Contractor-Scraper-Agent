# api/auth.py
# JWT + password hashing utilities and the FastAPI dependency that guards routes.

import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from dotenv import load_dotenv

load_dotenv()

JWT_SECRET = os.getenv("JWT_SECRET", "dev-insecure-change-me-please-set-JWT_SECRET-in-env")
JWT_ALG = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

# tokenUrl is only used by FastAPI's OpenAPI page; the actual endpoint is /api/auth/login
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


# ──────────────────────────────────────────────────────────────
# Password helpers
# ──────────────────────────────────────────────────────────────
def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────
# Token helpers
# ──────────────────────────────────────────────────────────────
def create_access_token(payload: Dict[str, Any], expires_hours: Optional[int] = None) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=expires_hours or JWT_EXPIRE_HOURS)
    to_encode = {**payload, "exp": exp}
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> Dict[str, Any]:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])


# ──────────────────────────────────────────────────────────────
# FastAPI dependency — attaches user to request, 401 if missing/invalid
# ──────────────────────────────────────────────────────────────
async def get_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> Dict[str, Any]:
    cred_err = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing authentication token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise cred_err
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise cred_err

    email = payload.get("sub")
    if not email:
        raise cred_err

    return {
        "email": email,
        "name": payload.get("name"),
        "user_id": payload.get("user_id"),
    }
