"""Application time policy.

The business timezone is Moscow.  Datetimes are stored as timezone-aware UTC
values, while API/business integrations use Moscow local time.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_moscow() -> datetime:
    return now_utc().astimezone(MOSCOW_TZ)


def to_moscow(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=MOSCOW_TZ)
    return value.astimezone(MOSCOW_TZ)


def normalize_moscow_input(value: datetime | None) -> datetime | None:
    """Normalize an API datetime to the Moscow business timezone.

    A timezone-aware value represents an instant and must be converted rather
    than having its offset discarded.  A naive value is accepted for backwards
    compatibility and is interpreted as a Moscow wall-clock value.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=MOSCOW_TZ)
    return value.astimezone(MOSCOW_TZ)
