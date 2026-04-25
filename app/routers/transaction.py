from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
import httpx
import uuid
from fastapi import APIRouter, HTTPException, Depends, Body

from app.ai_service import parse_transaction
from app.middleware.auth import decode_access_token

router = APIRouter(prefix="/transaction", tags=["transaction"])
bearer_scheme = HTTPBearer()

# ── Prompt / AI ───────────────────────────────────────────────────────────────

class PromptRequest(BaseModel):
    text: str
    user_id: int

class TransactionData(BaseModel):
    type: str
    amount: float
    currency: str
    address: Optional[str] = None
    wallet: str = "cash"
    date_time: str
    category: str
    # New fields from Novita/Llama schema
    content: Optional[str] = None
    tags: Optional[str] = None
    notes: Optional[str] = None
    date: Optional[str] = None      # YYYY-MM-DD

class PromptResponse(BaseModel):
    request_id: str
    user_prompt: str
    data: TransactionData
    
    # ── AI Prompt ─────────────────────────────────────────────────────────────────

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> dict:
    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload

def require_user(payload: dict = Depends(get_current_user)) -> dict:
    return payload

@router.post("/prompt", response_model=PromptResponse)
# Depends(require_user) is JWT authentication pattern for FastAPI
async def process_prompt(body: PromptRequest, payload: dict = Depends(require_user)):
    uid = int(payload["sub"])

    # Fetch user's preferred currency so the AI can default to it
    # with get_db() as conn:
    #     with conn.cursor() as cur:
    #         cur.execute("SELECT currency_code FROM users WHERE id=%s", (uid,))
    #         row = cur.fetchone()
    # currency = row["currency_code"] if row else "VND"

    currency = "VND"  # For now, hardcode to VND until we implement user preferences
    try:
        data = await parse_transaction(body.text, currency)
    except ValueError as e:
        # Non-JSON or schema error from the model
        raise HTTPException(422, f"AI returned unparseable output: {e}")
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"AI provider error: {e.response.status_code}")
    except httpx.TimeoutException:
        raise HTTPException(504, "AI provider timed out")
    except Exception as e:
        raise HTTPException(500, f"AI processing failed: {e}")

    # Map the parsed fields onto the TransactionData schema.
    # The new schema adds content/tags/notes; existing fields are preserved.
    transaction_data = {
        "type":      data["type"],
        "amount":    float(data["amount"]),
        "currency":  data["currency"],
        "address":   data.get("address") or data.get("content"),
        "wallet":    data.get("wallet", "cash"),
        "date_time": data["date_time"],
        "category":  data["category"],
        # Extra fields returned as-is; Flutter can pick them up
        "content":   data.get("content"),
        "tags":      data.get("tags"),
        "notes":     data.get("notes"),
        "date":      data.get("date"),
    }

    return PromptResponse(
        request_id=str(uuid.uuid4()),
        user_prompt=body.text,
        data=transaction_data,
    )