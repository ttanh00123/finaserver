# app/repositories/initialize_service.py

from app.db.database import Database
from app.repositories.category_repository import CategoryRepository
from app.repositories.wallet_repository import WalletRepository


# Tên ví Cash mặc định theo locale
_CASH_WALLET_NAMES = {
    "vi": "Tiền mặt",
    "en": "Cash",
    "ja": "現金",
    "ko": "현금",
    "zh": "现金",
}

# Màu mặc định cho Cash wallet
_CASH_WALLET_COLOR = "#1D9E75"


class InitializeService:

    @staticmethod
    def initialize_user(user_id: int, locale: str, currency: str) -> None:
        """
        Khởi tạo dữ liệu mặc định cho user mới:
        1. Copy master_categories → categories của user (đúng locale, fallback 'en')
        2. Tạo Cash wallet mặc định
        3. Update user status = 9 (ready to use)

        Idempotent — gọi lại không tạo duplicate.
        """
        # ── 1. Copy master categories ──────────────────────────────────────
        if not CategoryRepository.has_categories(user_id):
            masters = CategoryRepository.get_master_with_translation(locale)

            if not masters:
                raise ValueError(
                    f"No master categories found for locale '{locale}' or fallback 'en'"
                )

            rows = [
                (
                    user_id,
                    m["name"],
                    m["icon"],
                    m["type"],
                    m["sort_order"],
                    m["master_id"],
                )
                for m in masters
            ]
            CategoryRepository.bulk_create(rows)

        # ── 2. Tạo Cash wallet mặc định ───────────────────────────────────
        if not WalletRepository.has_wallets(user_id):
            cash_name = _CASH_WALLET_NAMES.get(locale)
            if cash_name is None:
                # Fallback: lấy tên tiếng Anh
                cash_name = _CASH_WALLET_NAMES["en"]

            WalletRepository.create(
                user_id=user_id,
                name=cash_name,
                wallet_type="wallet_type.cash",
                currency=currency,
                color=_CASH_WALLET_COLOR,
                sort_order=1,
            )

        # ── 3. Update user status → 9 (ready to use) ──────────────────────
        Database.execute(
            "UPDATE users SET status = %s WHERE id = %s",
            (9, user_id),
        )