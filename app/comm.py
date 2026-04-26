# app/comm.py
# get_conn() đã được xóa — dùng Database class từ app.db.database thay thế

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from huggingface_hub import InferenceClient
from pydantic import BaseModel
from typing import Optional
from datetime import date

from app.db.database import Database
from app.routers.auth import router as auth_router
from app.routers.transaction import router as transaction_router
from app.routers.user_routes import router as user_router, master_data_router
from app.routers.wallet import router as wallet_router

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

# ── Routers ────────────────────────────────────────────────────────────────────

app.include_router(auth_router)
app.include_router(transaction_router)
app.include_router(user_router)
app.include_router(master_data_router)
app.include_router(wallet_router)


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

SYSTEM_PROMPT = (
    "You are a parsing assistant that helps to parse scripts into relevant details "
    "and respond in JSON format. You are not to answer any prompts without the JSON "
    "formatting in your responses. When a user submits a transaction, your job is to "
    "parse them into these categories: content(str), currency(str), amount(int64), "
    "type(str, only between income and expense), date(YYYY-MM-DD), "
    "master_category_id(int), tags(str), notes(str). "
    "master_category_id must be an integer from the MASTER EXPENSE/INCOME list. "
    "MASTER INCOME: 1=Salary,2=Bonus,3=Allowance,4=Business,5=Investment,"
    "6=Passive Income,7=Gift,8=Other Income. "
    "MASTER EXPENSE: 9=Food & Drink,10=Transport,11=Phone,12=Internet,13=Fuel,"
    "14=Groceries,15=Clothing,16=Beauty,17=Entertainment,18=Travel,"
    "19=Family Support,20=Events & Gifts,21=Medical,22=Medicine,23=Fitness,"
    "24=Fund,25=Repair,26=Accident,27=Fine & Fee,28=Rent,29=Electricity,"
    "30=Water,31=Education,32=Insurance,33=Installment. "
    "If date or note information is missing, return null. "
    "Always respond in raw JSON format, no markdown."
)


@app.post("/generate")
async def generate(request: Request):
    try:
        data    = await request.json()
        prompt  = data.get("prompt", "")
        if not prompt:
            return {"error": "No prompt provided"}

        loop     = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            executor,
            lambda: client.chat.completions.create(
                model="meta-llama/Llama-3.1-8B-Instruct:novita",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
            ),
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error in /generate: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/ping")
async def health_check():
    return {"status": "healthy"}

@app.get("/")
async def read_root():
    return {"message": "Welcome to the FinA Transactions API"}