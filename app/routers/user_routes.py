# app/routes/user_routes.py

import hashlib
import json
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.db.database import Database
from app.middleware.auth import get_current_user_id
from app.repositories.category_repository import CategoryRepository
from app.repositories.wallet_repository import WalletRepository
from app.services.initialize_service import InitializeService


router             = APIRouter(prefix="/users",       tags=["users"])
master_data_router = APIRouter(prefix="/master-data", tags=["master-data"])


class InitializeRequest(BaseModel):
    locale:   str = "en"
    currency: str = "USD"


@router.post("/initialize", status_code=200)
async def initialize(
    body:    InitializeRequest,
    user_id: int = Depends(get_current_user_id),
):
    """
    Bước 2 sau signup: user chọn locale + currency trên OnboardingScreen.
    - Copy master_categories → categories của user
    - Tạo Cash wallet mặc định
    - Set user.status = 9 (ready to use)
    """
    locale   = body.locale.strip().lower()
    currency = body.currency.strip().upper()

    # Fallback 'en' nếu locale chưa có translation
    supported = {r["locale"] for r in Database.fetch_all(
        "SELECT DISTINCT locale FROM master_category_translations"
    )}
    if locale not in supported:
        locale = "en"

    InitializeService.initialize_user(
        user_id=user_id,
        locale=locale,
        currency=currency,
    )

    return {"status": "ok"}


@master_data_router.get("/sync")
async def sync_master_data(
    client_md5: Optional[str] = Query(default=None),
    user_id:    int           = Depends(get_current_user_id),
):
    """
    So sánh MD5 client vs server.
    - Khớp  → { changed: false }
    - Khác  → { changed: true, md5, data: { wallets, categories } }
    """
    data       = _build_master_data(user_id)
    server_md5 = _compute_md5(data)

    # Upsert hash để debug/monitor
    Database.execute(
        """
        INSERT INTO user_master_data_hash (userid, md5_hash)
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE md5_hash = VALUES(md5_hash), updated_at = NOW()
        """,
        (user_id, server_md5),
    )

    if client_md5 == server_md5:
        return {"changed": False, "md5": server_md5}

    return {"changed": True, "md5": server_md5, "data": data}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_master_data(user_id: int) -> dict:
    return {
        "wallets":    _serialize_wallets(WalletRepository.get_by_user(user_id)),
        "categories": _serialize_categories(CategoryRepository.get_by_user(user_id)),
    }


def _serialize_wallets(wallets: list[dict]) -> list[dict]:
    return [{
        "id":             w["id"],
        "userid":         w["userid"],
        "name":           w["name"],
        "wallet_type":    w["wallet_type"],
        "currency":       w["currency"],
        "balance":        float(w["balance"]),
        "account_number": w.get("account_number"),
        "bank_name":      w.get("bank_name"),
        "credit_limit":   float(w["credit_limit"]) if w.get("credit_limit") else None,
        "status":         w["status"],
        "sort_order":     w["sort_order"],
        "color":          w.get("color"),
        "due_day":        w.get("due_day"),
        "created_at":     w["created_at"].isoformat() if w.get("created_at") else None,
    } for w in wallets]


def _serialize_categories(categories: list[dict]) -> list[dict]:
    return [{
        "id":         c["id"],
        "userid":     c["userid"],
        "name":       c["name"],
        "icon":       c["icon"],
        "type":       c["type"],
        "sort_order": c["sort_order"],
        "master_id":  c.get("master_id"),
    } for c in categories]


def _compute_md5(data: dict) -> str:
    payload = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()