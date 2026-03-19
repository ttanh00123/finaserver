# repositories/user_repository.py
from typing import Optional

from passlib.context import CryptContext
from app.db.database import Database
from app.utils.password import verify_password
class UserRepository:

    @staticmethod
    def get_by_id(user_id: int) -> Optional[dict]:
        return Database.fetch_one(
            "SELECT * FROM users WHERE id = %s",
            (user_id,),
        )

    @staticmethod
    def get_by_email(email: str) -> Optional[dict]:
        return Database.fetch_one(
            "SELECT * FROM users WHERE email = %s",
            (email,),
        )

    @staticmethod
    def get_by_email_password(email: str, password: str) -> Optional[dict]:
      user = Database.fetch_one(
          "SELECT * FROM users WHERE email = %s", (email,)
      )
      print(f"Fetched user: {user} / {password} / user['password_hash']: {user['password_hash'] if user else None}")
      if not user or not verify_password(password, user["password_hash"]):
          print("Password verification failed")
          return None
      return user

    @staticmethod
    def create(email: str, password_hash: str, display_name: str) -> int:
        """Trả về id của user vừa tạo"""
        return Database.execute(
            "INSERT INTO users (email, password_hash, display_name) VALUES (%s, %s, %s)",
            (email, password_hash, display_name),
        )

    @staticmethod
    def update_display_name(user_id: int, display_name: str) -> bool:
        rows = Database.execute(
            "UPDATE users SET display_name = %s WHERE id = %s",
            (display_name, user_id),
        )
        return rows > 0

    @staticmethod
    def delete(user_id: int) -> bool:
        rows = Database.execute(
            "DELETE FROM users WHERE id = %s",
            (user_id,),
        )
        return rows > 0