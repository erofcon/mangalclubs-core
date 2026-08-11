from __future__ import annotations

from datetime import datetime, timedelta

from app.core.config import settings


MIN_TBANK_REDIRECT_DUE_SECONDS = 60


def get_minimum_payment_deadline(now: datetime) -> datetime:
    return now + timedelta(seconds=MIN_TBANK_REDIRECT_DUE_SECONDS)


def get_minimum_scheduled_order_time(now: datetime) -> datetime:
    """Earliest order time that still leaves enough time to pay."""
    return get_minimum_payment_deadline(now) + timedelta(
        minutes=settings.order_unpaid_payment_deadline_minutes
    )
