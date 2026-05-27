from app.db.database import Database

def _recalculate_balance() -> None:
    """Gọi stored procedure recalc toàn bộ wallet balance."""
    Database.execute("CALL sp_recalculate_wallet_balance()")