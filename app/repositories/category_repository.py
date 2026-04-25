# app/repositories/category_repository.py

from typing import Optional
from app.db.database import Database


class CategoryRepository:

    @staticmethod
    def get_by_id(category_id: int) -> Optional[dict]:
        return Database.fetch_one(
            "SELECT * FROM categories WHERE id = %s",
            (category_id,),
        )

    @staticmethod
    def get_by_user(user_id: int) -> list[dict]:
        return Database.fetch_all(
            """
            SELECT * FROM categories
            WHERE userid = %s
            ORDER BY type, sort_order
            """,
            (user_id,),
        )

    @staticmethod
    def create(
        user_id: int,
        name: str,
        icon: str,
        type_: int,
        sort_order: int,
        master_id: Optional[int] = None,
    ) -> int:
        return Database.execute(
            """
            INSERT INTO categories (userid, name, icon, type, sort_order, master_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (user_id, name, icon, type_, sort_order, master_id),
        )

    @staticmethod
    def bulk_create(rows: list[tuple]) -> int:
        """
        rows: list of (userid, name, icon, type, sort_order, master_id)
        """
        return Database.execute_many(
            """
            INSERT INTO categories (userid, name, icon, type, sort_order, master_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            rows,
        )

    @staticmethod
    def update(category_id: int, user_id: int, name: str, icon: str) -> int:
        return Database.execute(
            """
            UPDATE categories
            SET name = %s, icon = %s
            WHERE id = %s AND userid = %s
            """,
            (name, icon, category_id, user_id),
        )

    @staticmethod
    def delete(category_id: int, user_id: int) -> int:
        return Database.execute(
            "DELETE FROM categories WHERE id = %s AND userid = %s",
            (category_id, user_id),
        )

    @staticmethod
    def get_master_with_translation(locale: str) -> list[dict]:
        """
        Lấy toàn bộ master categories với tên đã dịch theo locale.
        Fallback về 'en' nếu locale không tồn tại.
        """
        return Database.fetch_all(
            """
            SELECT
                mc.id           AS master_id,
                mc.icon,
                mc.type,
                mc.sort_order,
                COALESCE(
                    (SELECT name FROM master_category_translations
                     WHERE category_id = mc.id AND locale = %s),
                    (SELECT name FROM master_category_translations
                     WHERE category_id = mc.id AND locale = 'en')
                ) AS name
            FROM master_categories mc
            ORDER BY mc.type, mc.sort_order
            """,
            (locale,),
        )

    @staticmethod
    def has_categories(user_id: int) -> bool:
        row = Database.fetch_one(
            "SELECT COUNT(*) AS cnt FROM categories WHERE userid = %s",
            (user_id,),
        )
        return (row["cnt"] if row else 0) > 0