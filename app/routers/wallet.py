# app/routers/wallet.py

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db.database import Database
from app.middleware.auth import get_current_user_id
from app.repositories.wallet_repository import WalletRepository

router = APIRouter(prefix="/wallets", tags=["wallets"])


# ── Schemas ────────────────────────────────────────────────────────────────────

class WalletCreate(BaseModel):
    name:           str
    wallet_type:    str
    currency:       str            = "VND"
    color:          str            = "#1D9E75"
    balance:        float          = 0.0
    account_number: Optional[str]  = None
    bank_name:      Optional[str]  = None
    credit_limit:   Optional[float] = None
    due_day:        Optional[int]  = None

class WalletUpdate(BaseModel):
    name:           Optional[str]   = None
    color:          Optional[str]   = None
    account_number: Optional[str]   = None
    bank_name:      Optional[str]   = None
    credit_limit:   Optional[float] = None
    due_day:        Optional[int]   = None
    sort_order:     Optional[int]   = None


# ── GET /wallets ───────────────────────────────────────────────────────────────

@router.get("")
async def get_wallets(user_id: int = Depends(get_current_user_id)):
    wallets = WalletRepository.get_by_user(user_id)
    return [_serialize(w) for w in wallets]


# ── POST /wallets ──────────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_wallet(
    body:    WalletCreate,
    user_id: int = Depends(get_current_user_id),
):
    sort_order = WalletRepository.get_next_sort_order(user_id)
    wallet_id  = WalletRepository.create(
        user_id=user_id,
        name=body.name,
        wallet_type=body.wallet_type,
        currency=body.currency,
        color=body.color,
        balance=body.balance,
        sort_order=sort_order,
        account_number=body.account_number,
        bank_name=body.bank_name,
        credit_limit=body.credit_limit,
        due_day=body.due_day,
    )

    # Sau khi tạo ví mới → invalidate MD5 để client sync lại
    _invalidate_md5(user_id)

    wallet = WalletRepository.get_by_id(wallet_id)
    return _serialize(wallet)


# ── PUT /wallets/:id ───────────────────────────────────────────────────────────

@router.put("/{wallet_id}")
async def update_wallet(
    wallet_id: int,
    body:      WalletUpdate,
    user_id:   int = Depends(get_current_user_id),
):
    existing = WalletRepository.get_by_id(wallet_id)
    if not existing or existing["userid"] != user_id:
        raise HTTPException(status_code=404, detail="Wallet not found")

    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if fields:
        WalletRepository.update(wallet_id, user_id, **fields)
        _invalidate_md5(user_id)

    wallet = WalletRepository.get_by_id(wallet_id)
    return _serialize(wallet)


# ── DELETE /wallets/:id ────────────────────────────────────────────────────────

@router.delete("/{wallet_id}", status_code=200)
async def delete_wallet(
    wallet_id: int,
    user_id:   int = Depends(get_current_user_id),
):
    existing = WalletRepository.get_by_id(wallet_id)
    if not existing or existing["userid"] != user_id:
        raise HTTPException(status_code=404, detail="Wallet not found")

    # Không cho xóa nếu đã có giao dịch
    if WalletRepository.has_transactions(wallet_id):
        raise HTTPException(
            status_code=409,
            detail="Không thể xóa ví đã có giao dịch",
        )

    # Không cho xóa ví duy nhất
    wallets = WalletRepository.get_by_user(user_id)
    if len(wallets) <= 1:
        raise HTTPException(
            status_code=409,
            detail="Không thể xóa ví duy nhất",
        )

    WalletRepository.soft_delete(wallet_id, user_id)
    _invalidate_md5(user_id)
    return {"status": "deleted"}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _serialize(w: dict) -> dict:
    return {
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
        "color":          w.get("color") or "#1D9E75",
        "due_day":        w.get("due_day"),
        "created_at":     w["created_at"].isoformat() if w.get("created_at") else None,
    }

def _invalidate_md5(user_id: int):
    """Xóa MD5 cache → lần sync tiếp theo client sẽ nhận data mới"""
    Database.execute(
        "DELETE FROM user_master_data_hash WHERE userid = %s",
        (user_id,),
    )