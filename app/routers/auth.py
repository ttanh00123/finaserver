# app/routers/auth.py
# Migrate từ get_conn() sang Database class
# Giữ nguyên toàn bộ logic + routes

import os
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from jose import jwt, JWTError
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr

from app.db.database import Database
from app.repositories.user_repository import UserRepository

load_dotenv("secrets.env")
load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────

pwd_context         = CryptContext(schemes=["bcrypt_sha256"], deprecated="auto")
JWT_SECRET          = os.getenv("AUTH_JWT_SECRET", "change-me")
JWT_EXPIRES_MINUTES = int(os.getenv("AUTH_JWT_EXPIRES_MINUTES", "60"))
JWT_ALG             = "HS256"

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Schemas ────────────────────────────────────────────────────────────────────

class SignupRequest(BaseModel):
    email:        EmailStr
    password:     str
    display_name: Optional[str] = None

class LoginRequest(BaseModel):
    email:    EmailStr
    password: str

class OAuthStartResponse(BaseModel):
    authorization_url: str

class OAuthCallbackRequest(BaseModel):
    code:  str
    state: Optional[str] = None

class OTPRequest(BaseModel):
    email: EmailStr

class OTPVerifyRequest(BaseModel):
    email:        EmailStr
    otp:          str
    new_password: Optional[str] = None

class TokenResponse(BaseModel):
    user_id:      Optional[int] = None
    status:       int           = 0
    access_token: str
    token_type:   str           = "bearer"

class LoginResultResponse(BaseModel):
    result:  bool
    user:    Dict[str, Any]
    message: Optional[str] = None
    token:   str

class TokenVerifyRequest(BaseModel):
    token: str

class TokenVerifyResponse(BaseModel):
    result: bool
    user:   Dict[str, Any]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _hash_password(password: str) -> str:
    return pwd_context.hash(password)

def _verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)

def _create_token(payload: Dict[str, Any]) -> str:
    to_encode        = payload.copy()
    to_encode["exp"] = datetime.utcnow() + timedelta(minutes=JWT_EXPIRES_MINUTES)
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALG)

def _decode_token(token: str) -> Dict[str, Any]:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])

# ── DB helpers — Database class thay thế get_conn() ──────────────────────────

def _get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    return Database.fetch_one(
        """
        SELECT id, email, password_hash, display_name,
               provider, provider_id, avatar, gender, status
        FROM users WHERE email = %s
        """,
        (email,),
    )

def _get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    return Database.fetch_one(
        """
        SELECT id, email, display_name, provider,
               avatar, gender, status
        FROM users WHERE id = %s
        """,
        (user_id,),
    )

def _insert_user(
    email:         str,
    password_hash: Optional[str],
    display_name:  Optional[str],
    provider:      str,
    provider_id:   Optional[str],
    status:        int = 0,
) -> int:
    return Database.execute(
        """
        INSERT INTO users (email, password_hash, display_name, provider, provider_id, status)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (email, password_hash, display_name, provider, provider_id, status),
    )

def _set_otp(email: str, otp: str, expires_at: datetime):
    Database.execute(
        "UPDATE users SET otp_code = %s, otp_expires_at = %s WHERE email = %s",
        (otp, expires_at, email),
    )

def _consume_otp(email: str, otp: str) -> bool:
    row = Database.fetch_one(
        "SELECT otp_code, otp_expires_at FROM users WHERE email = %s",
        (email,),
    )
    if not row:
        return False
    code, expires_at = row["otp_code"], row["otp_expires_at"]
    if not code or code != otp:
        return False
    if expires_at and datetime.utcnow() > expires_at:
        return False
    Database.execute(
        "UPDATE users SET otp_code = NULL, otp_expires_at = NULL WHERE email = %s",
        (email,),
    )
    return True

def _update_password(email: str, password_hash: str):
    Database.execute(
        "UPDATE users SET password_hash = %s WHERE email = %s",
        (password_hash, email),
    )

def _send_email_stub(email: str, subject: str, body: str):
    print(f"[EMAIL to {email}] {subject}\n{body}")


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/signup", response_model=TokenResponse, status_code=201)
async def signup(payload: SignupRequest):
    if _get_user_by_email(payload.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    user_id = _insert_user(
        payload.email,
        _hash_password(payload.password),
        payload.display_name,
        provider="local",
        provider_id=None,
    )
    token = _create_token({"sub": str(user_id), "email": payload.email})
    return TokenResponse(user_id=user_id, access_token=token, status=0)


@router.post("/login", response_model=LoginResultResponse)
async def login(payload: LoginRequest):
    user = UserRepository.get_by_email_password(payload.email, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = _create_token({"sub": str(user["id"]), "email": user["email"]})
    return LoginResultResponse(
        result=True,
        user={
            "id":           user["id"],
            "email":        user["email"],
            "display_name": user["display_name"],
            "avatar":       user.get("avatar"),
            "gender":       user.get("gender"),
            "status":       user.get("status", 0),
        },
        message="Login successful",
        token=token,
    )


@router.post("/login/token", response_model=TokenVerifyResponse)
async def verify_login_token(payload: TokenVerifyRequest):
    try:
        claims = _decode_token(payload.token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user_id_str = claims.get("sub")
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Invalid token claims")
    user = UserRepository.get_by_id(int(user_id_str))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return TokenVerifyResponse(
        result=True,
        user={
            "id":           user["id"],
            "email":        user["email"],
            "display_name": user["display_name"],
            "avatar":       user.get("avatar"),
            "gender":       user.get("gender"),
            "status":       user.get("status", 0),
        },
    )


@router.get("/oauth/google/start", response_model=OAuthStartResponse)
async def google_start():
    client_id    = os.getenv("OAUTH_GOOGLE_CLIENT_ID", "")
    redirect_uri = os.getenv("OAUTH_GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/oauth/google/callback")
    return OAuthStartResponse(authorization_url=(
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={client_id}&redirect_uri={redirect_uri}"
        "&response_type=code&scope=openid email profile&access_type=offline"
    ))


@router.post("/oauth/google/callback", response_model=TokenResponse)
async def google_callback(payload: OAuthCallbackRequest):
    client_id     = os.getenv("OAUTH_GOOGLE_CLIENT_ID")
    client_secret = os.getenv("OAUTH_GOOGLE_CLIENT_SECRET")
    redirect_uri  = os.getenv("OAUTH_GOOGLE_REDIRECT_URI", "http://localhost:8001/auth/oauth/google/callback")
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="Google OAuth not configured")
    async with httpx.AsyncClient() as c:
        res = await c.post("https://oauth2.googleapis.com/token", data={
            "code": payload.code, "client_id": client_id,
            "client_secret": client_secret, "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })
        if res.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to exchange code")
        try:
            claims = jwt.decode(res.json().get("id_token"), options={"verify_signature": False})
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid ID token")
    email    = claims.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Email not provided by Google")
    user     = _get_user_by_email(email)
    user_id  = _insert_user(email, None, claims.get("name"), "google", claims.get("sub")) if not user else int(user["id"])
    return TokenResponse(access_token=_create_token({"sub": str(user_id), "email": email}))


@router.get("/oauth/facebook/start", response_model=OAuthStartResponse)
async def facebook_start():
    client_id    = os.getenv("OAUTH_FACEBOOK_CLIENT_ID", "")
    redirect_uri = os.getenv("OAUTH_FACEBOOK_REDIRECT_URI", "http://localhost:8000/auth/oauth/facebook/callback")
    return OAuthStartResponse(authorization_url=(
        f"https://www.facebook.com/v11.0/dialog/oauth"
        f"?client_id={client_id}&redirect_uri={redirect_uri}&response_type=code&scope=email,public_profile"
    ))


@router.post("/oauth/facebook/callback", response_model=TokenResponse)
async def facebook_callback(payload: OAuthCallbackRequest):
    email   = f"facebook_user_{payload.code}@example.com"
    user    = _get_user_by_email(email)
    user_id = _insert_user(email, None, None, "facebook", email) if not user else int(user["id"])
    return TokenResponse(access_token=_create_token({"sub": str(user_id), "email": email}))


@router.post("/password/otp/request")
async def request_otp(payload: OTPRequest):
    if not _get_user_by_email(payload.email):
        raise HTTPException(status_code=404, detail="User not found")
    otp = f"{secrets.randbelow(999999):06d}"
    _set_otp(payload.email, otp, datetime.utcnow() + timedelta(minutes=10))
    _send_email_stub(payload.email, "Your OTP Code", f"Your OTP is {otp}. It expires in 10 minutes.")
    return {"message": "OTP sent"}


@router.post("/password/otp/verify", response_model=TokenResponse)
async def verify_otp(payload: OTPVerifyRequest):
    user = _get_user_by_email(payload.email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not _consume_otp(payload.email, payload.otp):
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")
    if payload.new_password:
        _update_password(payload.email, _hash_password(payload.new_password))
    return TokenResponse(access_token=_create_token({"sub": str(user["id"]), "email": user["email"]}))


@router.post("/logout")
async def logout():
    return {"message": "Logged out"}