from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import date
import mysql.connector
from openai import OpenAI
from starlette.middleware.wsgi import WSGIMiddleware
from app.auth_service import router as auth_router
from dotenv import load_dotenv
import os

# Load environment variables from secrets.env
load_dotenv('.env')

app = FastAPI()

# Mount auth router
app.include_router(auth_router)

client = OpenAI(
    base_url="https://router.huggingface.co/v1",
    api_key=os.getenv('AI_APIKEY'),
)

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


@app.post("/generate")
async def generate(request: Request):
    data = await request.json()
    prompt = data.get("prompt", "")
    if not prompt:
        return {"error": "No prompt provided"}
    response = client.chat.completions.create(
    model="meta-llama/Llama-3.2-3B-Instruct:novita",
    messages=[
        {
            "role": "system", 
            "content": "You are a parsing assistant that helps to parse scripts into relevant details and respond in JSON format. You are not to answer any prompts without the JSON formatting in your responses. When a user submit a transaction, your job is to parse them into these categories: content(str), currency(str), amount(int64), type(str, only between income and expense), date(YYYY-MM-DD), category(str), tags(str), notes(str). Available categories include (Food & Drinks, Education, Transportation, Health, Entertainment, Utilities, Devices, Others). Available tags include (Personal, Family, Work). If date or note information is missing, return null for those fields. Always return just a string for the values of each keys. THE CONTENT FIELD SHOULD NOT CONTAIN ANY OTHER DETAILS (e.g new phone for 500USD is NOT a valid content field, but new phone is). USE THE CONTENT'S CONTEXT to fill in the category and tags field (e.g 'breakfast of banh mi' means Food and Drinks category and Personal tag while 'november tuition fees' means Education category and Family tag). Always respond in raw JSON format and do not tamper it with Markdown or other formatting methods. DO NOT RESPOND LIKE A NORMAL CHAT AI IN ANY CIRCUMSTANCES."
        },
        {
            "role": "user",
            "content": prompt
        },    
    ],
    )    
    print(response.choices[0].message.content)
    return response.choices[0].message.content

# Ping
@app.get("/ping")
async def health_check():
    return {"status": "healthy"}

@app.get("/")
async def read_root():
    return {"message": "Welcome to the FinA Transactions API"}

