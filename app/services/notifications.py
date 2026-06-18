from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.base import utcnow
from app.models.customer import Customer, CustomerDevice
from app.models.order import CustomerOrderNotification, Order
from app.schemas.notification import CustomerDeviceRegisterIn


logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
ORDER_NOTIFICATION_EVENTS = {"order_created", "pickup_ready", "delivery_on_way", "delivery_delivered"}


async def register_customer_device(
    db: AsyncSession,
    customer: Customer,
    payload: CustomerDeviceRegisterIn,
) -> CustomerDevice:
    device = await db.scalar(
        select(CustomerDevice).where(
            CustomerDevice.customer_id == customer.id,
            CustomerDevice.device_id == payload.device_id,
        )
    )
    now = utcnow()

    if device is None:
        device = CustomerDevice(
            customer_id=customer.id,
            device_id=payload.device_id,
            push_token=payload.push_token,
            platform=payload.platform,
            device_name=payload.device_name,
            last_seen_at=now,
            is_active=True,
        )
        db.add(device)
    else:
        device.push_token = payload.push_token
        device.platform = payload.platform
        device.device_name = payload.device_name
        device.last_seen_at = now
        device.is_active = True

    await db.commit()
    await db.refresh(device)
    return device


async def deactivate_customer_device(db: AsyncSession, customer: Customer, device_id: str) -> None:
    await db.execute(
        update(CustomerDevice)
        .where(
            CustomerDevice.customer_id == customer.id,
            CustomerDevice.device_id == device_id,
        )
        .values(is_active=False, last_seen_at=utcnow())
    )
    await db.commit()


async def list_customer_unread_notifications(
    db: AsyncSession,
    customer: Customer,
    *,
    limit: int = 50,
) -> list[CustomerOrderNotification]:
    result = await db.scalars(
        select(CustomerOrderNotification)
        .where(
            CustomerOrderNotification.customer_id == customer.id,
            CustomerOrderNotification.is_read.is_(False),
        )
        .order_by(CustomerOrderNotification.created_at.desc())
        .limit(limit)
    )
    return list(result)


async def mark_customer_order_notifications_read(
    db: AsyncSession,
    customer: Customer,
    *,
    order_id,
) -> int:
    result = await db.execute(
        update(CustomerOrderNotification)
        .where(
            CustomerOrderNotification.customer_id == customer.id,
            CustomerOrderNotification.order_id == order_id,
            CustomerOrderNotification.is_read.is_(False),
        )
        .values(is_read=True, read_at=utcnow())
    )
    await db.commit()
    return result.rowcount or 0


async def ensure_order_notification(
    db: AsyncSession,
    order: Order,
    event_type: str,
    *,
    send_push: bool = True,
) -> CustomerOrderNotification | None:
    if event_type not in ORDER_NOTIFICATION_EVENTS or order.customer_id is None:
        return None

    existing = await db.scalar(
        select(CustomerOrderNotification).where(
            CustomerOrderNotification.order_id == order.id,
            CustomerOrderNotification.event_type == event_type,
        )
    )
    if existing is not None:
        return existing

    title, body = build_order_notification_text(order, event_type)
    statement = (
        insert(CustomerOrderNotification)
        .values(
            customer_id=order.customer_id,
            order_id=order.id,
            event_type=event_type,
            title=title,
            body=body,
        )
        .on_conflict_do_nothing(
            index_elements=[
                CustomerOrderNotification.order_id,
                CustomerOrderNotification.event_type,
            ]
        )
        .returning(CustomerOrderNotification.id)
    )
    notification_id = await db.scalar(statement)
    if notification_id is None:
        return await db.scalar(
            select(CustomerOrderNotification).where(
                CustomerOrderNotification.order_id == order.id,
                CustomerOrderNotification.event_type == event_type,
            )
        )

    notification = await db.get(CustomerOrderNotification, notification_id)
    if notification is None:
        return None

    if send_push:
        await send_order_push(db, order, notification)

    return notification


async def send_order_push(
    db: AsyncSession,
    order: Order,
    notification: CustomerOrderNotification,
) -> None:
    result = await db.scalars(
        select(CustomerDevice).where(
            CustomerDevice.customer_id == order.customer_id,
            CustomerDevice.is_active.is_(True),
        )
    )
    devices = [device for device in result if is_expo_push_token(device.push_token)]
    if not devices:
        return

    messages = [
        {
            "to": device.push_token,
            "sound": "default",
            "title": notification.title,
            "body": notification.body,
            "data": {
                "type": "order",
                "orderId": str(order.id),
                "publicNumber": order.public_number,
                "eventType": notification.event_type,
            },
        }
        for device in devices
    ]

    try:
        timeout = httpx.Timeout(settings.expo_push_request_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(EXPO_PUSH_URL, json=messages)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        notification.push_error = {"message": str(exc)}
        logger.warning("Expo push failed for order %s: %s", order.id, exc)
        return

    notification.push_sent_at = utcnow()
    notification.push_error = None


def build_order_notification_text(order: Order, event_type: str) -> tuple[str, str]:
    number = order.public_number

    if event_type == "order_created":
        return "Заказ принят", f"Заказ №{number} появился в профиле."
    if event_type == "pickup_ready":
        return "Заказ готов", f"Заказ №{number} готов к выдаче."
    if event_type == "delivery_on_way":
        return "Курьер в пути", f"Заказ №{number} передан в доставку."
    if event_type == "delivery_delivered":
        return "Заказ доставлен", f"Заказ №{number} доставлен."

    return "Статус заказа обновлен", f"Заказ №{number} обновлен."


def is_expo_push_token(value: str) -> bool:
    return value.startswith("ExponentPushToken[") or value.startswith("ExpoPushToken[")
