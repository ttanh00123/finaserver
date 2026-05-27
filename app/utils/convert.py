from datetime import datetime, timezone

def _parse_dt(value: str | None) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        dt_utc = dt.astimezone(timezone.utc)
        return dt_utc.strftime('%Y-%m-%d %H:%M:%S')  # → "2026-05-24 23:00:00"
    except ValueError:
        return value