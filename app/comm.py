from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import date
import mysql.connector
from starlette.middleware.wsgi import WSGIMiddleware
from app.auth_service import router as auth_router
from dotenv import load_dotenv
import os

# Load environment variables from secrets.env
load_dotenv('secrets.env')

app = FastAPI()

# Mount auth router
app.include_router(auth_router)


origins = ['*']

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database connection
def get_conn():
    return mysql.connector.connect(
        host=os.getenv('DB_SERVER'),
        port=int(os.getenv('DB_PORT', 3306)),
        database=os.getenv('DB_DATABASE'),
        user=os.getenv('DB_USERNAME'),
        password=os.getenv('DB_PASSWORD'),
    )


class Transaction(BaseModel):
    content: str
    currency: str
    amount: float
    type: str
    date: Optional[str] = None
    category: str
    tags: str
    notes: Optional[str] = None
    user_id: int

@app.post("/addTransaction")
async def add_transaction(transaction: Transaction):
    try:
        conn = get_conn()
        cursor = conn.cursor()
        # Fill optional fields with defaults if missing
        tx_date = transaction.date
        if not tx_date:
            tx_date = date.today().isoformat()
        if tx_date == 'null':
            tx_date = date.today().isoformat()
        tx_notes = transaction.notes
        if tx_notes is None:
            tx_notes = 'None'

        print(transaction)
        cursor.execute('''
            INSERT INTO transactions (content, currency, amount, type, date, category, tags, notes, userid)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (transaction.content, transaction.currency, transaction.amount, transaction.type, tx_date, transaction.category, transaction.tags, tx_notes, transaction.user_id))
        conn.commit()
        conn.close()
        return {"message": "Transaction added successfully"}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/transactions")
async def get_transactions(user_id: int):
    try:
        conn = get_conn()
        cursor = conn.cursor()
        print(user_id)
        cursor.execute('SELECT * FROM transactions WHERE userid = %s', (user_id,))
        rows = cursor.fetchall()
        transactions = []
        for row in rows:
            transactions.append({
                "id": row[0],
                "content": row[1],
                "currency": row[2],
                "amount": row[3],
                "type": row[4],
                "date": row[5],
                "category": row[6],
                "tags": row[7],
                "notes": row[8],
                "user_id": row[9] if len(row) > 9 else None
            })
        conn.close()
        return transactions
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Delete function to remove selected transaction
@app.delete("/deleteTransaction/{transaction_id}")
async def delete_transaction(transaction_id: int):
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM transactions WHERE id = %s', (transaction_id,))
        conn.commit()
        if cursor.rowcount == 0:
            conn.close()
            raise HTTPException(status_code=404, detail="Transaction not found")
        conn.close()
        return {"message": "Transaction deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Update function to modify existing transaction
@app.put("/updateTransaction/{transaction_id}")
async def update_transaction(transaction_id: int, transaction: Transaction):
    try:
        conn = get_conn()
        cursor = conn.cursor()
        
        # Check if transaction exists
        cursor.execute('SELECT id FROM transactions WHERE id = %s', (transaction_id,))
        if not cursor.fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="Transaction not found")
        
        # Optional fields filter
        tx_date = transaction.date
        if not tx_date:
            tx_date = date.today().isoformat()
        if tx_date == 'null':
            tx_date = date.today().isoformat()
        
        tx_notes = transaction.notes
        if tx_notes is None:
            tx_notes = 'None'
        
        cursor.execute('''
            UPDATE transactions
            SET content = %s, currency = %s, amount = %s, type = %s, date = %s, category = %s, tags = %s, notes = %s
            WHERE id = %s
        ''', (transaction.content, transaction.currency, transaction.amount, transaction.type, tx_date, transaction.category, transaction.tags, tx_notes, transaction_id))
        conn.commit()
        conn.close()
        
        return {"message": "Transaction updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Ping
@app.get("/ping")
async def health_check():
    return {"status": "healthy"}

@app.get("/")
async def read_root():
    return {"message": "Welcome to the FinA Transactions API"}

