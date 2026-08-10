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
    """Normalize client input as Moscow wall-clock time.

    Offset information supplied by a client is deliberately ignored: the
    backend is the source of truth and scheduled restaurant times are entered
    in Moscow time.  The resulting value is timezone-aware and suitable for
    UTC storage.
    """
    if value is None:
        return None
    return value.replace(tzinfo=None).replace(tzinfo=MOSCOW_TZ)
