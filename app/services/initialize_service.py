# app/services/initialize_service.py

from app.db.database import Database
from app.repositories.wallet_repository import WalletRepository

_CASH_WALLET_NAMES = {
    "vi": "Tiền mặt",
    "en": "Cash",
    "ja": "現金",
    "ko": "현금",
    "zh": "现金",
}
_CASH_WALLET_COLOR = "#1D9E75"


class InitializeService:

    @staticmethod
    def initialize_user(user_id: int, locale: str, currency: str) -> None:
        # Chỉ tạo Cash wallet mặc định — không copy categories nữa
        if not WalletRepository.has_wallets(user_id):
            WalletRepository.create(
                user_id=user_id,
                name=_CASH_WALLET_NAMES.get(locale, _CASH_WALLET_NAMES["en"]),
                wallet_type="wallet_type.cash",
                currency=currency,
                color=_CASH_WALLET_COLOR,
                sort_order=1,
            )

        # Update user status = 9 (ready to use)
        Database.execute(
            "UPDATE users SET status = %s WHERE id = %s",
            (9, user_id),
        )