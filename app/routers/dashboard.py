# ── 1. Tạo View trong MySQL ────────────────────────────────────────────────────
# Chạy SQL này 1 lần trong DB

"""
-- View tính total balance per user (bao gồm balance ban đầu + tất cả transactions)
CREATE OR REPLACE VIEW v_user_balance AS
SELECT
    w.userid,
    w.currency,
    -- Số dư ban đầu của ví + Thu nhập + Tiền nhận chuyển khoản - Chi tiêu
    SUM(
        COALESCE(w.balance, 0) -- Giả định w.balance lưu số dư ban đầu lúc tạo ví
        + COALESCE((SELECT SUM(CAST(t.amount AS DECIMAL(15,2))) FROM transactions t WHERE t.wallet_id = w.id AND t.type = 1 AND t.status = 0), 0)
        + COALESCE((SELECT SUM(CAST(t.amount AS DECIMAL(15,2))) FROM transactions t WHERE t.to_wallet_id = w.id AND t.status = 0), 0)
        - COALESCE((SELECT SUM(CAST(t.amount AS DECIMAL(15,2))) FROM transactions t WHERE t.wallet_id = w.id AND t.type = 0 AND t.status = 0), 0)
    ) AS total_balance
FROM wallets w
WHERE w.status = 1
GROUP BY w.userid, w.currency;

-- View tính income/expense theo period (không tính transfer)
CREATE OR REPLACE VIEW v_transaction_summary AS
SELECT
    t.userid,
    t.type,
    t.currency,
    DATE_FORMAT(t.date_time, '%Y') AS year,
    QUARTER(t.date_time)           AS quarter,
    DATE_FORMAT(t.date_time, '%Y-%m') AS month,
    SUM(t.amount) AS total
FROM transactions t
WHERE t.type IN (0, 1)   -- chỉ expense và income, không có transfer
  AND t.status = 0
GROUP BY t.userid, t.type, t.currency,
         DATE_FORMAT(t.date_time, '%Y'),
         QUARTER(t.date_time),
         DATE_FORMAT(t.date_time, '%Y-%m');
"""

# ── 2. app/routers/dashboard.py ───────────────────────────────────────────────

from datetime import datetime
from fastapi import APIRouter, Depends, Query
from typing import Optional

from app.db.database import Database
from app.middleware.auth import get_current_user_id

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
async def get_summary(
    period: str = Query(default="month", regex="^(year|quarter|month)$"),
    user_id: int = Depends(get_current_user_id),
):
    now = datetime.now()

    # ── Total balance từ View mới (Đã tính toán động) ──────────────────────────
    balance_rows = Database.fetch_all(
        "SELECT total_balance, currency FROM v_user_balance WHERE userid = %s",
        (user_id,),
    )

    # ── Xác định điều kiện lọc theo period ──────────────────────────────────────
    if period == "year":
        where_period = "year = %s"
        period_params = (str(now.year),)
    elif period == "quarter":
        where_period = "year = %s AND quarter = %s"
        period_params = (str(now.year), str((now.month - 1) // 3 + 1))
    else:  # month
        where_period = "month = %s"
        period_params = (now.strftime("%Y-%m"),)

    # ── Lấy dữ liệu summary thu/chi ───────────────────────────────────────────
    summary_rows = Database.fetch_all(
        f"""
        SELECT type, currency, SUM(total) AS total
        FROM v_transaction_summary
        WHERE userid = %s AND {where_period}
        GROUP BY type, currency
        """,
        (user_id, *period_params),
    )

    # ── Recent transactions ────────────────────────────────────────────────────
    recent = Database.fetch_all(
        """
        SELECT
            t.id, t.type, t.amount, t.currency,
            t.content, t.notes, t.date_time,
            t.category_id, t.wallet_id,
            w.name  AS wallet_name,
            w.color AS wallet_color,
            w.wallet_type
        FROM transactions t
        LEFT JOIN wallets w ON t.wallet_id = w.id
        WHERE t.userid = %s
        ORDER BY t.date_time DESC
        LIMIT 10
        """,
        (user_id,),
    )

    # ── Serialize dữ liệu an toàn cho đa tiền tệ ────────────────────────────────
    income = {}
    expense = {}
    
    for r in summary_rows:
        curr = r["currency"]
        val = float(r["total"])
        if r["type"] == 1:
            income[curr] = val
        elif r["type"] == 0:
            expense[curr] = val

    return {
        "period": period,
        "total_balance": [
            {"currency": r["currency"], "amount": float(r["total_balance"])}
            for r in balance_rows
        ],
        "income":  income,   # Trả về đúng format: { "VND": 5000000.0 }
        "expense": expense,  # Trả về đúng format: { "VND": 3080000.0 }
        "recent_transactions": [
            {
                "id":           r["id"],
                "type":         r["type"],
                "amount":       float(r["amount"]),
                "currency":     r["currency"],
                "content":      r.get("content") or r.get("notes"),
                "date_time":    r["date_time"].isoformat() if r.get("date_time") else None,
                "category_id":  r.get("category_id"),
                "wallet_id":    r.get("wallet_id"),
                "wallet_name":  r.get("wallet_name"),
                "wallet_color": r.get("wallet_color"),
                "wallet_type":  r.get("wallet_type"),
            }
            for r in recent
        ],
    }