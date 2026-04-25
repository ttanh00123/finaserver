# app/middleware/auth.py

from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
import os

# ── Config ─────────────────────────────────────────────────────────────────────

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
ALGORITHM  = os.getenv("JWT_ALGORITHM", "HS256")

_bearer = HTTPBearer()


# ── Core decode ────────────────────────────────────────────────────────────────

def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── Dependency: inject vào route bằng Depends() ───────────────────────────────

def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> int:
    """
    Dùng trong route:
        user_id: int = Depends(get_current_user_id)
    """
    payload = decode_token(credentials.credentials)

    user_id = payload.get("sub") or payload.get("user_id") or payload.get("id")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing user identity",
        )
    return int(user_id)


def get_current_payload(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """
    Trả về toàn bộ payload nếu route cần nhiều hơn user_id.
        payload: dict = Depends(get_current_payload)
    """
    return decode_token(credentials.credentials)