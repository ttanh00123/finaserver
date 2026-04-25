# app/db/database.py

import os
from contextlib import contextmanager
from typing import Any, Optional
import mysql.connector
from mysql.connector.pooling import MySQLConnectionPool
from dotenv import load_dotenv

load_dotenv("secrets.env")
load_dotenv()


class Database:
    _pool: MySQLConnectionPool = None

    @classmethod
    def _get_pool(cls) -> MySQLConnectionPool:
        if cls._pool is None:
            cls._pool = MySQLConnectionPool(
                pool_name="main_pool",
                pool_size=10,
                host=os.getenv("DB_SERVER"),
                port=int(os.getenv("DB_PORT", 3306)),
                database=os.getenv("DB_DATABASE"),
                user=os.getenv("DB_USERNAME"),
                password=os.getenv("DB_PASSWORD"),
                charset="utf8mb4",
                autocommit=False,
            )
        return cls._pool

    @classmethod
    @contextmanager
    def _get_connection(cls):
        conn = cls._get_pool().get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @classmethod
    def _row_to_dict(cls, cursor, row: tuple) -> dict[str, Any]:
        columns = [col[0] for col in cursor.description]
        return dict(zip(columns, row))

    @classmethod
    def fetch_one(cls, sql: str, params: tuple = ()) -> Optional[dict[str, Any]]:
        with cls._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            row = cursor.fetchone()
            if row is None:
                return None
            return cls._row_to_dict(cursor, row)

    @classmethod
    def fetch_all(cls, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with cls._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            return [cls._row_to_dict(cursor, row) for row in rows]

    @classmethod
    def execute(cls, sql: str, params: tuple = ()) -> int:
        with cls._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return cursor.lastrowid or cursor.rowcount

    @classmethod
    def execute_many(cls, sql: str, params_list: list[tuple]) -> int:
        with cls._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(sql, params_list)
            return cursor.rowcount