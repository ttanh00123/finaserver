# app/routers/transaction.py

import uuid
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.ai_service import parse_transaction
from app.db.database import Database
from app.middleware.auth import get_current_user_id, decode_access_token
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

router = APIRouter(prefix="/transactions", tags=["transactions"])
bearer_scheme = HTTPBearer()


# ── Auth helper (backward compat với code cũ) ─────────────────────────────────

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload


# ── Schemas ────────────────────────────────────────────────────────────────────

class TransactionCreate(BaseModel):
    type:            int
    wallet_id:       int
    amount:          float
    currency:        str            = "VND"
    to_wallet_id:    Optional[int]  = None
    receive_amount:  Optional[float] = None
    category_id:     Optional[int]  = None
    address:         Optional[str]  = None
    note:            Optional[str]  = None
    date_time:       Optional[str]  = None
    tags:            Optional[str]  = None
    temp_bill_keys:  Optional[list] = None
    request_id:      Optional[str]  = None

class TransactionUpdate(BaseModel):
    type:           Optional[int]   = None
    wallet_id:      Optional[int]   = None
    amount:         Optional[float] = None
    currency:       Optional[str]   = None
    to_wallet_id:   Optional[int]   = None
    receive_amount: Optional[float] = None
    category_id:    Optional[int]   = None
    address:        Optional[str]   = None
    note:           Optional[str]   = None
    date_time:      Optional[str]   = None
    tags:           Optional[str]   = None

class PromptRequest(BaseModel):
    text:    str
    user_id: int

class PromptResponse(BaseModel):
    request_id:  str
    user_prompt: str
    data:        dict


# ── POST /transactions ─────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_transaction(
    body:    TransactionCreate,
    user_id: int = Depends(get_current_user_id),
):
    # date_time mặc định NOW() nếu không truyền
    date_time = body.date_time or None

    tx_id = Database.execute(
        """
        INSERT INTO transactions
            (userid, type, wallet_id, to_wallet_id, amount, receive_amount,
             currency, category_id, content, notes, date_time, tags, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                COALESCE(%s, NOW()), %s, 0)
        """,
        (
            user_id,
            body.type,
            body.wallet_id,
            body.to_wallet_id,
            body.amount,
            body.receive_amount,
            body.currency,
            body.category_id,
            body.address,       # lưu vào content
            body.note,
            date_time,
            body.tags,
        ),
    )

    # TODO: move bill images từ temp → s3/<user_id>/bills/<tx_id>_<ts>.jpg
    # if body.temp_bill_keys:
    #     BillService.move_to_permanent(tx_id, user_id, body.temp_bill_keys)

    # Cập nhật balance ví
    _update_wallet_balance(body.wallet_id, body.amount, body.type)
    if body.type == 2 and body.to_wallet_id:  # transfer
        receive = body.receive_amount or body.amount
        _update_wallet_balance(body.to_wallet_id, receive, income=True)

    return {"id": tx_id, "status": "created"}


# ── GET /transactions ──────────────────────────────────────────────────────────

@router.get("")
async def get_transactions(
    limit:       int           = Query(default=50,  ge=1, le=200),
    offset:      int           = Query(default=0,   ge=0),
    type:        Optional[int] = Query(default=None),
    wallet_id:   Optional[int] = Query(default=None),
    category_id: Optional[int] = Query(default=None),
    from_date:   Optional[str] = Query(default=None),
    to_date:     Optional[str] = Query(default=None),
    user_id:     int           = Depends(get_current_user_id),
):
    conditions = ["userid = %s"]
    params     = [user_id]

    if type        is not None: conditions.append("type = %s");        params.append(type)
    if wallet_id   is not None: conditions.append("wallet_id = %s");   params.append(wallet_id)
    if category_id is not None: conditions.append("category_id = %s"); params.append(category_id)
    if from_date:               conditions.append("date_time >= %s");  params.append(from_date)
    if to_date:                 conditions.append("date_time <= %s");  params.append(to_date)

    where = " AND ".join(conditions)
    params += [limit, offset]

    rows = Database.fetch_all(
        f"""
        SELECT
            t.id, t.type, t.wallet_id, t.to_wallet_id,
            t.amount, t.receive_amount, t.currency,
            t.category_id, t.content, t.notes,
            t.date_time, t.tags, t.status,
            w.name AS wallet_name, w.color AS wallet_color,
            w.wallet_type
        FROM transactions t
        LEFT JOIN wallets w ON t.wallet_id = w.id
        WHERE {where}
        ORDER BY t.date_time DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params),
    )

    return [_serialize_transaction(r) for r in rows]


# ── GET /transactions/:id ──────────────────────────────────────────────────────

@router.get("/{tx_id}")
async def get_transaction(
    tx_id:   int,
    user_id: int = Depends(get_current_user_id),
):
    row = Database.fetch_one(
        """
        SELECT
            t.id, t.type, t.wallet_id, t.to_wallet_id,
            t.amount, t.receive_amount, t.currency,
            t.category_id, t.content, t.notes,
            t.date_time, t.tags, t.status,
            w.name AS wallet_name, w.color AS wallet_color,
            w.wallet_type
        FROM transactions t
        LEFT JOIN wallets w ON t.wallet_id = w.id
        WHERE t.id = %s AND t.userid = %s
        """,
        (tx_id, user_id),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return _serialize_transaction(row)


# ── PUT /transactions/:id ──────────────────────────────────────────────────────

@router.put("/{tx_id}")
async def update_transaction(
    tx_id:   int,
    body:    TransactionUpdate,
    user_id: int = Depends(get_current_user_id),
):
    existing = Database.fetch_one(
        "SELECT * FROM transactions WHERE id = %s AND userid = %s",
        (tx_id, user_id),
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Transaction not found")

    # Chỉ update các field được truyền (partial update)
    updates = {}
    if body.type           is not None: updates["type"]           = body.type
    if body.wallet_id      is not None: updates["wallet_id"]      = body.wallet_id
    if body.amount         is not None: updates["amount"]         = body.amount
    if body.currency       is not None: updates["currency"]       = body.currency
    if body.to_wallet_id   is not None: updates["to_wallet_id"]   = body.to_wallet_id
    if body.receive_amount is not None: updates["receive_amount"] = body.receive_amount
    if body.category_id    is not None: updates["category_id"]    = body.category_id
    if body.address        is not None: updates["content"]        = body.address
    if body.note           is not None: updates["notes"]          = body.note
    if body.date_time      is not None: updates["date_time"]      = body.date_time
    if body.tags           is not None: updates["tags"]           = body.tags

    if not updates:
        return {"id": tx_id, "status": "no_changes"}

    set_clause = ", ".join(f"{k} = %s" for k in updates)
    params     = list(updates.values()) + [tx_id, user_id]

    Database.execute(
        f"UPDATE transactions SET {set_clause} WHERE id = %s AND userid = %s",
        tuple(params),
    )
    return {"id": tx_id, "status": "updated"}


# ── DELETE /transactions/:id ───────────────────────────────────────────────────

@router.delete("/{tx_id}", status_code=204)
async def delete_transaction(
    tx_id:   int,
    user_id: int = Depends(get_current_user_id),
):
    affected = Database.execute(
        "DELETE FROM transactions WHERE id = %s AND userid = %s",
        (tx_id, user_id),
    )
    if not affected:
        raise HTTPException(status_code=404, detail="Transaction not found")


# ── POST /transactions/prompt (AI parse) ──────────────────────────────────────

@router.post("/prompt")
async def process_prompt(
    body:    PromptRequest,
    payload: dict = Depends(get_current_user),
):
    uid      = int(payload["sub"])
    currency = "VND"

    try:
        data = await parse_transaction(body.text, currency)
    except ValueError as e:
        raise HTTPException(422, f"AI returned unparseable output: {e}")
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"AI provider error: {e.response.status_code}")
    except httpx.TimeoutException:
        raise HTTPException(504, "AI provider timed out")
    except Exception as e:
        raise HTTPException(500, f"AI processing failed: {e}")

    return PromptResponse(
        request_id=str(uuid.uuid4()),
        user_prompt=body.text,
        data={
            "type":              data.get("type"),
            "amount":            float(data.get("amount", 0)),
            "currency":          data.get("currency", currency),
            "address":           data.get("address") or data.get("content"),
            "wallet":            data.get("wallet", "cash"),
            "date_time":         data.get("date_time"),
            "master_category_id": data.get("master_category_id"),
            "content":           data.get("content"),
            "tags":              data.get("tags"),
            "notes":             data.get("notes"),
        },
    )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _serialize_transaction(r: dict) -> dict:
    return {
        "id":             r["id"],
        "type":           r["type"],
        "wallet_id":      r["wallet_id"],
        "wallet_name":    r.get("wallet_name"),
        "wallet_color":   r.get("wallet_color"),
        "wallet_type":    r.get("wallet_type"),
        "to_wallet_id":   r.get("to_wallet_id"),
        "amount":         float(r["amount"]),
        "receive_amount": float(r["receive_amount"]) if r.get("receive_amount") else None,
        "currency":       r["currency"],
        "category_id":    r.get("category_id"),
        "content":        r.get("content"),
        "notes":          r.get("notes"),
        "date_time":      r["date_time"].isoformat() if r.get("date_time") else None,
        "tags":           r.get("tags"),
        "status":         r.get("status", 0),
    }


def _update_wallet_balance(wallet_id: int, amount: float, type: int = None, income: bool = False):
    """
    Cập nhật balance ví sau khi tạo transaction.
    type: 0=expense, 1=income, 2=transfer
    """
    if income or type == 1:
        Database.execute(
            "UPDATE wallets SET balance = balance + %s WHERE id = %s",
            (amount, wallet_id),
        )
    elif type == 0:
        Database.execute(
            "UPDATE wallets SET balance = balance - %s WHERE id = %s",
            (amount, wallet_id),
        )
    # type==2 (transfer): xử lý ở caller