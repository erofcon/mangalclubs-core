from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from fastapi import HTTPException, status

from app.core.time import MOSCOW_TZ
from app.models.organization import Organization, OrganizationWorkingHour


ORDERS_OPEN_MESSAGE = "Сейчас можно оформить онлайн-заказ."
NON_WORKING_DAY_MESSAGE = "Сегодня онлайн-заказы не принимаются."
OUTSIDE_WORKING_HOURS_MESSAGE = "Сейчас онлайн-заказы не принимаются. Пожалуйста, выберите другое время."


def get_organization_orders_availability(
    organization: Organization,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    local_now = get_local_now(now)
    current_weekday = local_now.weekday()
    current_time = local_now.time().replace(tzinfo=None)
    hours_by_weekday = {item.weekday: item for item in organization.working_hours}

    previous_hours = hours_by_weekday.get((current_weekday - 1) % 7)
    if previous_hours and is_previous_overnight_shift_open(previous_hours, current_time):
        return build_working_hours_availability(True, "working_hours_open", ORDERS_OPEN_MESSAGE)

    today_hours = hours_by_weekday.get(current_weekday)
    if today_hours is None or today_hours.is_closed:
        return build_working_hours_availability(False, "non_working_day", NON_WORKING_DAY_MESSAGE)

    if is_today_shift_open(today_hours, current_time):
        return build_working_hours_availability(True, "working_hours_open", ORDERS_OPEN_MESSAGE)

    return build_working_hours_availability(False, "outside_working_hours", OUTSIDE_WORKING_HOURS_MESSAGE)


def get_organization_order_time_slots(
    organization: Organization,
    *,
    target_date: date | None = None,
    step_minutes: int = 30,
) -> dict[str, Any]:
    local_timezone = get_local_timezone()
    slot_date = target_date or datetime.now(local_timezone).date()
    hours_by_weekday = {item.weekday: item for item in organization.working_hours}
    windows = build_order_time_windows(hours_by_weekday, slot_date, local_timezone)

    slot_pairs = [
        (starts_at, ends_at)
        for window_start, window_end in windows
        for starts_at, ends_at in split_window_into_slots(window_start, window_end, step_minutes)
    ]

    # Do not offer slots that have already passed today.  The rounding keeps
    # the same :00/:30 (or configured step) boundaries on the current day.
    local_now = get_local_now(None)
    if slot_date == local_now.date():
        current_minutes = local_now.hour * 60 + local_now.minute
        if local_now.second or local_now.microsecond:
            current_minutes += 1
        first_available_minutes = (
            (current_minutes + step_minutes - 1) // step_minutes
        ) * step_minutes
        first_available_at = datetime.combine(
            slot_date,
            time.min,
            tzinfo=local_timezone,
        ) + timedelta(minutes=first_available_minutes)
        slot_pairs = [
            (starts_at, ends_at)
            for starts_at, ends_at in slot_pairs
            if starts_at >= first_available_at
        ]

    return {
        "organization_id": organization.id,
        "slug": organization.slug,
        "date": slot_date,
        "timezone": str(getattr(local_timezone, "key", local_timezone)),
        "is_closed": not windows,
        "step_minutes": step_minutes,
        "working_hours": organization.working_hours,
        "windows": [{"starts_at": starts_at, "ends_at": ends_at} for starts_at, ends_at in windows],
        "slots": [{"starts_at": starts_at, "ends_at": ends_at} for starts_at, ends_at in slot_pairs],
    }


def ensure_organization_accepts_orders_now(organization: Organization) -> None:
    availability = get_organization_orders_availability(organization)
    if availability["orders_available"]:
        return

    raise HTTPException(status.HTTP_409_CONFLICT, availability["message"])


def ensure_order_time_slot_is_available(
    organization: Organization,
    complete_before: datetime,
    *,
    step_minutes: int = 30,
) -> None:
    """Validate a scheduled order against the server-generated Moscow slots."""
    local_complete_before = get_local_now(complete_before)
    if local_complete_before.second or local_complete_before.microsecond:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Selected order time must start on a minute boundary",
        )
    local_now = get_local_now(None)
    if local_complete_before <= local_now:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Selected order time is in the past",
        )

    schedule = get_organization_order_time_slots(
        organization,
        target_date=local_complete_before.date(),
        step_minutes=step_minutes,
    )

    if any(
        slot["starts_at"] == local_complete_before
        for slot in schedule["slots"]
    ):
        return

    raise HTTPException(
        status.HTTP_409_CONFLICT,
        "Selected order time is no longer available",
    )


def build_working_hours_availability(orders_available: bool, reason: str, message: str) -> dict[str, Any]:
    return {
        "orders_available": orders_available,
        "reason": reason,
        "message": message,
    }


def build_order_time_windows(
    hours_by_weekday: dict[int, OrganizationWorkingHour],
    slot_date: date,
    local_timezone,
) -> list[tuple[datetime, datetime]]:
    windows: list[tuple[datetime, datetime]] = []
    current_weekday = slot_date.weekday()
    day_start = datetime.combine(slot_date, time.min, tzinfo=local_timezone)
    day_end = day_start + timedelta(days=1)

    today_hours = hours_by_weekday.get(current_weekday)
    if today_hours and not today_hours.is_closed and today_hours.opens_at and today_hours.closes_at:
        starts_at = datetime.combine(slot_date, today_hours.opens_at, tzinfo=local_timezone)
        ends_at_date = slot_date + timedelta(days=1) if today_hours.closes_next_day else slot_date
        ends_at = datetime.combine(ends_at_date, today_hours.closes_at, tzinfo=local_timezone)
        windows.append((starts_at, ends_at))

    previous_hours = hours_by_weekday.get((current_weekday - 1) % 7)
    if (
        previous_hours
        and not previous_hours.is_closed
        and previous_hours.opens_at
        and previous_hours.closes_at
        and previous_hours.closes_next_day
    ):
        starts_at = datetime.combine(slot_date, time.min, tzinfo=local_timezone)
        ends_at = datetime.combine(slot_date, previous_hours.closes_at, tzinfo=local_timezone)
        windows.append((starts_at, ends_at))

    return merge_time_windows([
        (max(starts_at, day_start), min(ends_at, day_end))
        for starts_at, ends_at in sorted(windows)
        if max(starts_at, day_start) < min(ends_at, day_end)
    ])


def merge_time_windows(windows: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    merged: list[tuple[datetime, datetime]] = []

    for starts_at, ends_at in windows:
        if not merged or starts_at > merged[-1][1]:
            merged.append((starts_at, ends_at))
            continue

        previous_start, previous_end = merged[-1]
        merged[-1] = (previous_start, max(previous_end, ends_at))

    return merged


def split_window_into_slots(
    starts_at: datetime,
    ends_at: datetime,
    step_minutes: int,
) -> list[tuple[datetime, datetime]]:
    step = timedelta(minutes=step_minutes)
    slots: list[tuple[datetime, datetime]] = []
    cursor = starts_at

    while cursor < ends_at:
        slot_end = min(cursor + step, ends_at)
        slots.append((cursor, slot_end))
        cursor = slot_end

    return slots


def is_today_shift_open(working_hours: OrganizationWorkingHour, current_time) -> bool:
    if working_hours.is_closed or working_hours.opens_at is None or working_hours.closes_at is None:
        return False

    if working_hours.closes_next_day:
        return current_time >= working_hours.opens_at

    return working_hours.opens_at <= current_time < working_hours.closes_at


def is_previous_overnight_shift_open(working_hours: OrganizationWorkingHour, current_time) -> bool:
    if (
        working_hours.is_closed
        or working_hours.opens_at is None
        or working_hours.closes_at is None
        or not working_hours.closes_next_day
    ):
        return False

    return current_time < working_hours.closes_at


def get_local_now(now: datetime | None) -> datetime:
    local_timezone = get_local_timezone()
    if now is None:
        return datetime.now(local_timezone)
    if now.tzinfo is None:
        return now.replace(tzinfo=local_timezone)
    return now.astimezone(local_timezone)


def get_local_timezone():
    """Restaurant business time is always Moscow time."""
    return MOSCOW_TZ
