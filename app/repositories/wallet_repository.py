# # app/repositories/wallet_repository.py

# from typing import Optional
# from app.db.database import Database


# class WalletRepository:

#     @staticmethod
#     def get_by_id(wallet_id: int) -> Optional[dict]:
#         return Database.fetch_one(
#             "SELECT * FROM wallets WHERE id = %s",
#             (wallet_id,),
#         )

#     @staticmethod
#     def get_by_user(user_id: int) -> list[dict]:
#         return Database.fetch_all(
#             """
#             SELECT * FROM wallets
#             WHERE userid = %s AND status = 1
#             ORDER BY sort_order
#             """,
#             (user_id,),
#         )

#     @staticmethod
#     def create(
#         user_id: int,
#         name: str,
#         wallet_type: str,
#         currency: str,
#         color: str = "#1D9E75",
#         balance: float = 0.0,
#         sort_order: int = 0,
#     ) -> int:
#         return Database.execute(
#             """
#             INSERT INTO wallets
#                 (userid, name, wallet_type, currency, balance, color, status, sort_order)
#             VALUES (%s, %s, %s, %s, %s, %s, 1, %s)
#             """,
#             (user_id, name, wallet_type, currency, balance, color, sort_order),
#         )

#     @staticmethod
#     def has_wallets(user_id: int) -> bool:
#         row = Database.fetch_one(
#             "SELECT COUNT(*) AS cnt FROM wallets WHERE userid = %s AND status = 1",
#             (user_id,),
#         )
#         return (row["cnt"] if row else 0) > 0

# app/repositories/wallet_repository.py

from typing import Optional
from app.db.database import Database


class WalletRepository:

    @staticmethod
    def get_by_id(wallet_id: int) -> Optional[dict]:
        return Database.fetch_one(
            "SELECT * FROM wallets WHERE id = %s",
            (wallet_id,),
        )

    @staticmethod
    def get_by_user(user_id: int) -> list[dict]:
        return Database.fetch_all(
            """
            SELECT 
                w.*,
                -- Tính tổng thu nhập tại ví này
                COALESCE(SUM(CASE WHEN t.type = 1 AND t.wallet_id = w.id THEN CAST(t.amount AS DECIMAL(15,2)) ELSE 0 END), 0)
                -- Cộng với tổng tiền được chuyển từ ví khác đến ví này
                + COALESCE(SUM(CASE WHEN t.to_wallet_id = w.id THEN CAST(t.amount AS DECIMAL(15,2)) ELSE 0 END), 0)
                -- Trừ đi tổng chi tiêu tại ví này
                - COALESCE(SUM(CASE WHEN t.type = 0 AND t.wallet_id = w.id THEN CAST(t.amount AS DECIMAL(15,2)) ELSE 0 END), 0)
                AS balance
            FROM wallets w
            LEFT JOIN transactions t 
                ON w.id = t.wallet_id OR w.id = t.to_wallet_id
            WHERE w.userid = %s AND w.status = 1
            GROUP BY w.id
            ORDER BY w.sort_order;
            """,
            (user_id,),
        )

    @staticmethod
    def create(
        user_id:        int,
        name:           str,
        wallet_type:    str,
        currency:       str,
        color:          str            = "#1D9E75",
        balance:        float          = 0.0,
        sort_order:     int            = 0,
        account_number: Optional[str]  = None,
        bank_name:      Optional[str]  = None,
        credit_limit:   Optional[float] = None,
        due_day:        Optional[int]  = None,
    ) -> int:
        return Database.execute(
            """
            INSERT INTO wallets
                (userid, name, wallet_type, currency, balance, color,
                 status, sort_order, account_number, bank_name, credit_limit, due_day)
            VALUES (%s, %s, %s, %s, %s, %s, 1, %s, %s, %s, %s, %s)
            """,
            (user_id, name, wallet_type, currency, balance, color,
             sort_order, account_number, bank_name, credit_limit, due_day),
        )

    @staticmethod
    def update(wallet_id: int, user_id: int, **fields) -> int:
        if not fields:
            return 0
        set_clause = ", ".join(f"{k} = %s" for k in fields)
        params     = list(fields.values()) + [wallet_id, user_id]
        return Database.execute(
            f"UPDATE wallets SET {set_clause} WHERE id = %s AND userid = %s",
            tuple(params),
        )

    @staticmethod
    def soft_delete(wallet_id: int, user_id: int) -> int:
        return Database.execute(
            "UPDATE wallets SET status = 0 WHERE id = %s AND userid = %s",
            (wallet_id, user_id),
        )

    @staticmethod
    def has_transactions(wallet_id: int) -> bool:
        row = Database.fetch_one(
            """
            SELECT COUNT(*) AS cnt FROM transactions
            WHERE wallet_id = %s OR to_wallet_id = %s
            """,
            (wallet_id, wallet_id),
        )
        return (row["cnt"] if row else 0) > 0

    @staticmethod
    def has_wallets(user_id: int) -> bool:
        row = Database.fetch_one(
            "SELECT COUNT(*) AS cnt FROM wallets WHERE userid = %s AND status = 1",
            (user_id,),
        )
        return (row["cnt"] if row else 0) > 0

    @staticmethod
    def get_next_sort_order(user_id: int) -> int:
        row = Database.fetch_one(
            "SELECT COALESCE(MAX(sort_order), 0) + 1 AS next FROM wallets WHERE userid = %s",
            (user_id,),
        )
        return row["next"] if row else 1