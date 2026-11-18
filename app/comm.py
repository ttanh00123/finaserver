# app/comm.py
# get_conn() đã được xóa — dùng Database class từ app.db.database thay thế

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from huggingface_hub import InferenceClient
from pydantic import BaseModel
from typing import Optional
from datetime import date
from openai import OpenAI
from categories import EXPENSE, INCOME, FALLBACK

from app.db.database import Database
from app.routers.auth import router as auth_router
from app.routers.transaction import router as transaction_router
from app.routers.user_routes import router as user_router, master_data_router
from app.routers.wallet import router as wallet_router
from app.routers.dashboard import router as dashboard_router

load_dotenv("secrets.env")
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

executor = ThreadPoolExecutor(max_workers=5)

client = InferenceClient(api_key=os.environ["AI_API_KEY"])

app = FastAPI(title="FinA API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

parser_rules_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "parser_rules"))
if os.path.exists(parser_rules_dir):
    app.mount("/parser-rules", StaticFiles(directory=parser_rules_dir), name="parser_rules")

# ── Routers ────────────────────────────────────────────────────────────────────

app.include_router(auth_router)
app.include_router(transaction_router)
app.include_router(user_router)
app.include_router(master_data_router)
app.include_router(wallet_router)
app.include_router(dashboard_router)


# ── Legacy endpoints (dùng Database thay get_conn) ─────────────────────────────
# TODO: migrate sang TransactionRepository sau

class Transaction(BaseModel):
    content:  str
    currency: str
    amount:   float
    type:     str
    date:     Optional[str] = None
    category: str
    tags:     str
    notes:    Optional[str] = None
    user_id:  int


@app.post("/addTransaction")
async def add_transaction(transaction: Transaction):
    try:
        tx_date  = transaction.date or date.today().isoformat()
        if tx_date == "null":
            tx_date = date.today().isoformat()
        tx_notes = transaction.notes or "None"

        Database.execute(
            """
            INSERT INTO transactions (content, currency, amount, type, date_time, category_id, tags, notes, userid)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (transaction.content, transaction.currency, transaction.amount,
             transaction.type, tx_date, transaction.category,
             transaction.tags, tx_notes, transaction.user_id),
        )
        return {"message": "Transaction added successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/transactions")
async def get_transactions(user_id: int):
    try:
        rows = Database.fetch_all(
            "SELECT * FROM transactions WHERE userid = %s",
            (user_id,),
        )
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/deleteTransaction/{transaction_id}")
async def delete_transaction(transaction_id: int):
    try:
        affected = Database.execute(
            "DELETE FROM transactions WHERE id = %s",
            (transaction_id,),
        )
        if not affected:
            raise HTTPException(status_code=404, detail="Transaction not found")
        return {"message": "Transaction deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/updateTransaction/{transaction_id}")
async def update_transaction(transaction_id: int, transaction: Transaction):
    try:
        existing = Database.fetch_one(
            "SELECT id FROM transactions WHERE id = %s", (transaction_id,)
        )
        if not existing:
            raise HTTPException(status_code=404, detail="Transaction not found")

        tx_date  = transaction.date or date.today().isoformat()
        if tx_date == "null":
            tx_date = date.today().isoformat()
        tx_notes = transaction.notes or "None"

        Database.execute(
            """
            UPDATE transactions
            SET content=%s, currency=%s, amount=%s, type=%s,
                date_time=%s, category_id=%s, tags=%s, notes=%s
            WHERE id=%s
            """,
            (transaction.content, transaction.currency, transaction.amount,
             transaction.type, tx_date, transaction.category,
             transaction.tags, tx_notes, transaction_id),
        )
        return {"message": "Transaction updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── AI generate ────────────────────────────────────────────────────────────────

class Req(BaseModel):
    text: str
    type: str = "expense"          # "expense" or "income"
    locale: str = "vi"
    category_ids: list[int] = []   # accepted but ignored; the server owns the list


def build_prompt(kind: str) -> str:
    cats = INCOME if kind == "income" else EXPENSE
    lines = "\n".join(f"{i}: {name} ({hint})" for i, (name, hint) in cats.items())

    if kind == "income":
        examples = "luong thang 10 -> 1\nthuong tet -> 2\nlai tiet kiem -> 6"
    else:
        examples = (
            "pho bo -> 9\ngrab ve nha -> 10\ntien dien -> 29\n"
            "tien nha -> 28\nhoc phi -> 31\nthuoc cam -> 22\nmua ao -> 15"
        )

    return (
        f"You classify short personal finance {kind} notes, written in "
        "Vietnamese (with or without accents) or English, into exactly one category.\n"
        f"Categories (id: name):\n{lines}\n"
        "Rules:\n"
        "- Reply with ONLY the category id number, nothing else.\n"
        "- Dishes, drinks and snack names from any country are Food & Drink.\n"
        "- Use the Other id only if no category fits.\n"
        f"Examples:\n{examples}"
    )

PROMPTS = {"expense": build_prompt("expense"), "income": build_prompt("income")}

@app.post("/categorize")
def categorize(req: Req):
    kind = "income" if req.type == "income" else "expense"
    valid = set(INCOME if kind == "income" else EXPENSE)

    res = client.chat.completions.create(
        model="meta-llama/llama-3.2-3b-instruct:novita",
        messages=[
            {"role": "system", "content": PROMPTS[kind]},
            {"role": "user", "content": req.text},
        ],
        temperature=0,
        max_tokens=5,
    )

    raw = (res.choices[0].message.content or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    cid = int(digits) if digits else None

    if cid not in valid:
        cid = FALLBACK[kind]
    return {"category_id": cid}

# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/ping")
async def health_check():
    return {"status": "healthy"}

@app.get("/")
async def read_root():
    return {"message": "Welcome to the FinA Transactions API"}