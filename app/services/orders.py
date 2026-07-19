from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.base import utcnow
from app.models.customer import Customer
from app.models.menu import MenuItemContent
from app.models.order import CustomerOrderNotification, Order, TBankPayment, TBankPaymentEvent
from app.models.organization import Organization
from app.schemas.order import DeliveryPointIn, OrderCreateIn, OrderItemIn, OrderKind, OrderModifierIn
from app.services.availability import ensure_organization_accepts_orders_now
from app.services.delivery import ensure_delivery_available_for_coordinates
from app.services.iiko import (
    IikoAuthorizationError,
    IikoTerminalError,
    get_alive_iiko_terminal_group_id,
    get_valid_token,
    request_iiko_json,
)
from app.services.otp import InvalidPhoneNumberError, normalize_phone
from app.services.notifications import ensure_order_notification
from app.services.tbank import (
    TBankError,
    get_tbank_credentials,
    get_tbank_payment_state,
    init_tbank_payment,
    map_tbank_status,
    verify_tbank_token,
)


logger = logging.getLogger(__name__)


PICKUP_ORDER_SERVICE_TYPES = {"DeliveryByClient", "DeliveryPickUp"}
DELIVERY_ORDER_SERVICE_TYPES = {"DeliveryByCourier"}
PICKUP_READY_STATUSES = {"CookingCompleted", "Waiting"}
DELIVERY_ON_WAY_STATUSES = {"OnWay"}
DELIVERY_DELIVERED_STATUSES = {"Delivered", "Closed"}
FINAL_ORDER_STATUSES = {"Delivered", "Closed", "Cancelled"}
PAID_IIKO_RETRY_STATUSES = {"PaymentConfirmed", "IikoCreateFailed", "IikoCreateInProgress"}
IIKO_DISPATCH_IN_PROGRESS_TIMEOUT_SECONDS = 300
FINAL_PAYMENT_STATUSES = {"paid", "payment_failed", "payment_cancelled", "payment_expired"}
ACTIVE_PAYMENT_STATUSES = {"payment_pending", "payment_form_created"}
ARCHIVED_PAYMENT_STATUSES = {"payment_failed", "payment_cancelled", "payment_expired"}
MIN_TBANK_REDIRECT_DUE_SECONDS = 60
PUBLIC_ORDER_NUMBER_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
PUBLIC_ORDER_NUMBER_MIN_LENGTH = 6


async def create_order_payment(
    db: AsyncSession,
    payload: OrderCreateIn,
    customer: Customer | None = None,
) -> dict[str, Any]:
    order_phone = resolve_order_phone(payload, customer)
    organization = await resolve_order_organization(db, payload)
    delivery_calculation = await resolve_delivery_calculation(db, organization, payload)
    access_token = await get_order_access_token(db, organization)
    terminal_group_id = await get_order_terminal_group_id(access_token, organization)
    order_type = await get_iiko_order_type(access_token, organization, payload.order_type)
    credentials = get_tbank_credentials(organization)
    notification_url = resolve_tbank_notification_url()
    order_body = build_iiko_order_body(
        organization,
        payload,
        order_type["id"],
        order_phone=order_phone,
    )
    amount_kopecks = calculate_order_amount_kopecks(order_body, delivery_calculation=delivery_calculation)
    redirect_due_date = resolve_payment_redirect_due_date(payload.complete_before)
    local_order = await create_local_order(
        db,
        organization=organization,
        payload=payload,
        customer=customer,
        order_phone=order_phone,
        terminal_group_id=terminal_group_id,
        order_type=order_type,
        order_body=order_body,
        amount_kopecks=amount_kopecks,
        delivery_calculation=delivery_calculation,
    )

    payment = TBankPayment(
        order_id=local_order.id,
        organization_id=organization.id,
        terminal_key=credentials.terminal_key,
        bank_order_id=str(local_order.id),
        amount_kopecks=amount_kopecks,
        status="init_requested",
        init_request={
            "TerminalKey": credentials.terminal_key,
            "Amount": amount_kopecks,
            "OrderId": str(local_order.id),
            "NotificationURL": notification_url,
            "SuccessURL": payload.success_url or settings.tbank_success_url,
            "FailURL": payload.fail_url or settings.tbank_fail_url,
            "RedirectDueDate": redirect_due_date,
        },
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)

    try:
        data = await init_tbank_payment(
            credentials=credentials,
            amount_kopecks=amount_kopecks,
            bank_order_id=str(local_order.id),
            description=f"Order {local_order.public_number}",
            customer_key=str(customer.id) if customer is not None else None,
            notification_url=notification_url,
            success_url=payload.success_url or settings.tbank_success_url,
            fail_url=payload.fail_url or settings.tbank_fail_url,
            redirect_due_date=redirect_due_date,
            data={
                "localOrderId": str(local_order.id),
                "publicOrderNumber": local_order.public_number,
                "organizationId": str(organization.id),
                "organizationSlug": organization.slug,
            },
        )
    except TBankError as exc:
        payment.status = "payment_failed"
        payment.error_info = {"message": str(exc)}
        payment.failed_at = utcnow()
        local_order.payment_status = "payment_failed"
        local_order.payment_error_info = {"message": str(exc)}
        local_order.creation_status = "PaymentInitFailed"
        await db.commit()
        logger.warning("T-Bank payment init failed for order %s: %s", local_order.id, exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"T-Bank payment init failed: {exc}") from exc

    payment.bank_payment_id = optional_str(data.get("PaymentId"))
    payment.payment_url = optional_str(data.get("PaymentURL"))
    payment.status = map_tbank_status(data.get("Status"))
    payment.init_response = data
    local_order.payment_status = payment.status
    if payment.status == "paid":
        local_order.creation_status = "PaymentConfirmed"
        payment.paid_at = utcnow()
    await db.commit()
    await db.refresh(payment)
    await db.refresh(local_order)
    await ensure_order_notification(db, local_order, "order_created")
    await db.commit()
    logger.info(
        "Order payment created: order_id=%s public_number=%s organization_id=%s payment_id=%s status=%s amount_kopecks=%s",
        local_order.id,
        local_order.public_number,
        organization.id,
        payment.id,
        payment.status,
        amount_kopecks,
    )

    return {
        "id": local_order.id,
        "public_number": local_order.public_number,
        "customer_id": local_order.customer_id,
        "organization_id": organization.id,
        "organization_slug": organization.slug,
        "iiko_organization_id": organization.iiko_organization_id,
        "terminal_group_id": terminal_group_id,
        "order_type": payload.order_type,
        "iiko_order_type_id": order_type["id"],
        "iiko_order_service_type": order_type["orderServiceType"],
        "payment_status": local_order.payment_status,
        "total_sum": amount_kopecks / 100,
        "delivery": serialize_delivery_calculation(delivery_calculation),
        "payment": {
            "id": payment.id,
            "status": payment.status,
            "amount": amount_kopecks / 100,
            "amount_kopecks": amount_kopecks,
            "bank_order_id": payment.bank_order_id,
            "bank_payment_id": payment.bank_payment_id,
            "payment_url": payment.payment_url,
        },
    }


async def get_iiko_order_status(
    db: AsyncSession,
    *,
    order_id: str,
    organization_id,
    organization_slug: str | None,
    customer: Customer | None = None,
) -> dict[str, Any]:
    local_order = await resolve_local_status_order(db, order_id, customer=customer)
    if local_order is not None:
        if not local_order.iiko_order_id:
            return build_local_order_status(local_order)
        iiko_order_id = local_order.iiko_order_id
        organization = local_order.organization
        iiko_organization_id = local_order.iiko_organization_id
        if organization.iiko_organization_id != iiko_organization_id:
            return build_local_order_status(local_order)
    else:
        if customer is not None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
        iiko_order_id = order_id
        organization = await resolve_status_organization(
            db,
            organization_id=organization_id,
            organization_slug=organization_slug,
        )
        iiko_organization_id = organization.iiko_organization_id

    access_token = await get_order_access_token(db, organization)

    try:
        data = await request_iiko_json(
            "/api/1/deliveries/by_id",
            access_token,
            json_body={
                "organizationId": iiko_organization_id,
                "orderIds": [iiko_order_id],
            },
        )
    except IikoTerminalError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"iiko order status request failed: {exc}") from exc

    orders = data.get("orders")
    if not isinstance(orders, list):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "iiko did not return orders")

    order_info = next((item for item in orders if isinstance(item, dict) and item.get("id") == iiko_order_id), None)
    if order_info is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found in iiko")

    order = order_info.get("order") if isinstance(order_info.get("order"), dict) else {}
    order_status = order.get("status")
    order_type = detect_order_kind(order)
    notification_event = detect_notification_event(order_type, order_status)

    if local_order is not None:
        previous_notification_event = local_order.notification_event
        update_local_order_from_status_response(local_order, data, order_info, order, notification_event)
        if notification_event and notification_event != previous_notification_event:
            await ensure_order_notification(db, local_order, notification_event)
        await db.commit()
        await db.refresh(local_order)

    return {
        "id": local_order.id if local_order is not None else None,
        "public_number": local_order.public_number if local_order is not None else None,
        "correlation_id": data.get("correlationId"),
        "organization_id": organization.id,
        "organization_slug": organization.slug,
        "iiko_organization_id": iiko_organization_id,
        "order_type": order_type,
        "iiko_order_id": iiko_order_id,
        "creation_status": order_info.get("creationStatus"),
        "order_status": order_status,
        "payment_status": local_order.payment_status if local_order is not None else None,
        "payment_amount_kopecks": local_order.payment_amount_kopecks if local_order is not None else None,
        "number": order.get("number"),
        "sum": parse_float(order.get("sum")),
        "complete_before": order.get("completeBefore"),
        "comment": order.get("comment"),
        "notification_event": notification_event,
        "should_notify_customer": notification_event is not None,
        "error_info": normalize_error_info(order_info.get("errorInfo")),
    }


async def list_stored_orders(db: AsyncSession, *, limit: int, offset: int) -> list[Order]:
    result = await db.scalars(
        select(Order)
        .options(selectinload(Order.organization))
        .order_by(Order.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result)


async def list_customer_current_orders(db: AsyncSession, customer: Customer, *, limit: int, offset: int) -> list[dict[str, Any]]:
    await expire_customer_overdue_unpaid_orders(db, customer)

    result = await db.scalars(
        select(Order)
        .options(
            selectinload(Order.organization).selectinload(Organization.iiko_menu_snapshot),
            selectinload(Order.payments),
        )
        .where(
            Order.customer_id == customer.id,
            Order.creation_status != "Error",
            Order.payment_status.not_in(ARCHIVED_PAYMENT_STATUSES),
            or_(Order.order_status.is_(None), Order.order_status.not_in(FINAL_ORDER_STATUSES)),
        )
        .order_by(Order.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return await serialize_customer_orders(db, list(result))


async def list_customer_order_history(db: AsyncSession, customer: Customer, *, limit: int, offset: int) -> list[dict[str, Any]]:
    await expire_customer_overdue_unpaid_orders(db, customer)

    result = await db.scalars(
        select(Order)
        .options(
            selectinload(Order.organization).selectinload(Organization.iiko_menu_snapshot),
            selectinload(Order.payments),
        )
        .where(
            Order.customer_id == customer.id,
            or_(
                Order.creation_status == "Error",
                Order.payment_status.in_(ARCHIVED_PAYMENT_STATUSES),
                Order.order_status.in_(FINAL_ORDER_STATUSES),
            ),
        )
        .order_by(Order.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return await serialize_customer_orders(db, list(result))


async def get_stored_order(db: AsyncSession, order_id) -> Order:
    statement = select(Order).options(selectinload(Order.organization))
    if isinstance(order_id, UUID):
        statement = statement.where(Order.id == order_id)
    else:
        statement = statement.where(Order.public_number == normalize_public_order_number(order_id))

    order = await db.scalar(statement)
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")

    return order


async def serialize_customer_orders(db: AsyncSession, orders: list[Order]) -> list[dict[str, Any]]:
    if not orders:
        return []

    contents = await list_active_menu_item_contents(db)
    iiko_item_content = {content.iiko_item_id: content for content in contents if content.iiko_item_id}
    sku_content = {content.sku: content for content in contents if content.sku}
    unread_order_ids = await list_unread_order_notification_ids(db, orders)

    return [
        serialize_customer_order(
            order,
            iiko_item_content=iiko_item_content,
            sku_content=sku_content,
            unread_order_ids=unread_order_ids,
        )
        for order in orders
    ]


async def list_unread_order_notification_ids(db: AsyncSession, orders: list[Order]) -> set:
    order_ids = [order.id for order in orders]
    if not order_ids:
        return set()

    result = await db.scalars(
        select(CustomerOrderNotification.order_id).where(
            CustomerOrderNotification.order_id.in_(order_ids),
            CustomerOrderNotification.is_read.is_(False),
        )
    )
    return set(result)


async def list_active_menu_item_contents(db: AsyncSession) -> list[MenuItemContent]:
    result = await db.scalars(
        select(MenuItemContent)
        .where(MenuItemContent.is_active.is_(True))
        .order_by(MenuItemContent.sort_order, MenuItemContent.created_at)
    )
    return list(result)


def serialize_customer_order(
    order: Order,
    *,
    iiko_item_content: dict[str, MenuItemContent],
    sku_content: dict[str, MenuItemContent],
    unread_order_ids: set,
) -> dict[str, Any]:
    return {
        "id": order.id,
        "public_number": order.public_number,
        "organization_id": order.organization_id,
        "organization_slug": order.organization_slug,
        "order_type": order.order_type,
        "phone": order.phone,
        "comment": order.comment,
        "complete_before": order.complete_before,
        "guests_count": order.guests_count,
        "delivery_point": order.delivery_point,
        "items": enrich_order_items(
            order,
            iiko_item_content=iiko_item_content,
            sku_content=sku_content,
        ),
        "payment_status": order.payment_status,
        "payment_amount_kopecks": order.payment_amount_kopecks,
        "payment": serialize_customer_order_payment(order),
        "iiko_order_id": order.iiko_order_id,
        "iiko_external_number": order.iiko_external_number,
        "creation_status": order.creation_status,
        "order_status": order.order_status,
        "notification_event": order.notification_event,
        "has_unread_notification": order.id in unread_order_ids,
        "total_sum": float(order.total_sum) if order.total_sum is not None else None,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
    }


def serialize_customer_order_payment(order: Order) -> dict[str, Any] | None:
    if order.payment_status not in ACTIVE_PAYMENT_STATUSES:
        return None

    payment = next((item for item in order.payments if item.is_active and item.payment_url), None)
    if payment is None:
        return None

    return {
        "id": payment.id,
        "status": payment.status,
        "amount": payment.amount_kopecks / 100,
        "amount_kopecks": payment.amount_kopecks,
        "bank_order_id": payment.bank_order_id,
        "bank_payment_id": payment.bank_payment_id,
        "payment_url": payment.payment_url,
    }


def enrich_order_items(
    order: Order,
    *,
    iiko_item_content: dict[str, MenuItemContent],
    sku_content: dict[str, MenuItemContent],
) -> list[Any]:
    items = order.items if isinstance(order.items, list) else []
    organization = order.organization
    snapshot = organization.iiko_menu_snapshot if organization else None
    raw_menu = snapshot.raw_menu if snapshot and isinstance(snapshot.raw_menu, dict) else None
    menu_items = build_order_menu_item_index(raw_menu, order.iiko_organization_id)

    return [
        enrich_order_item(
            item,
            menu_items,
            iiko_item_content=iiko_item_content,
            sku_content=sku_content,
        )
        for item in items
    ]


def enrich_order_item(
    item: Any,
    menu_items: dict[tuple[str, str | None], dict[str, Any]],
    *,
    iiko_item_content: dict[str, MenuItemContent],
    sku_content: dict[str, MenuItemContent],
) -> Any:
    if not isinstance(item, dict):
        return item

    product_id = optional_str(item.get("productId") or item.get("product_id"))
    product_size_id = optional_str(item.get("productSizeId") or item.get("product_size_id"))
    enriched = dict(item)
    menu_item = find_order_menu_item(menu_items, product_id, product_size_id)

    sku = optional_str(menu_item.get("sku")) if menu_item else None
    content = iiko_item_content.get(product_id) if product_id else None
    if content is None and sku:
        content = sku_content.get(sku)

    name = content.name_override if content and content.name_override else None
    image = content.image_url if content and content.image_url else None
    if menu_item is not None:
        name = name or optional_str(menu_item.get("name"))
        image = image or optional_str(menu_item.get("image"))
        enriched.setdefault("sku", sku)
        enriched.setdefault("sizeName", menu_item.get("sizeName"))

    enriched["name"] = name
    enriched["image"] = image
    return enriched


def build_order_menu_item_index(raw_menu: dict[str, Any] | None, iiko_organization_id: str) -> dict[tuple[str, str | None], dict[str, Any]]:
    if not raw_menu:
        return {}

    menu_items: dict[tuple[str, str | None], dict[str, Any]] = {}
    for category in raw_menu.get("itemCategories") or []:
        if not isinstance(category, dict):
            continue
        for item in category.get("items") or []:
            if not isinstance(item, dict):
                continue

            item_id = optional_str(item.get("itemId") or item.get("id"))
            if not item_id:
                continue

            sku = optional_str(item.get("sku"))
            for item_size in item.get("itemSizes") or []:
                if not isinstance(item_size, dict):
                    continue

                size_id = optional_str(item_size.get("sizeId"))
                menu_items[(item_id, size_id)] = {
                    "name": optional_str(item.get("name")),
                    "image": optional_str(item_size.get("buttonImageUrl") or item.get("buttonImageUrl")),
                    "sku": sku,
                    "sizeName": optional_str(item_size.get("sizeName")),
                }

    return menu_items


def find_order_menu_item(
    menu_items: dict[tuple[str, str | None], dict[str, Any]],
    product_id: str | None,
    product_size_id: str | None,
) -> dict[str, Any] | None:
    if not product_id:
        return None

    if (product_id, product_size_id) in menu_items:
        return menu_items[(product_id, product_size_id)]
    if (product_id, None) in menu_items:
        return menu_items[(product_id, None)]
    return next((value for (item_id, _), value in menu_items.items() if item_id == product_id), None)


async def list_order_payment_events(db: AsyncSession, order_id) -> list[TBankPaymentEvent]:
    result = await db.scalars(
        select(TBankPaymentEvent)
        .where(TBankPaymentEvent.order_id == order_id)
        .order_by(TBankPaymentEvent.created_at.desc())
    )
    return list(result)


async def handle_tbank_webhook(db: AsyncSession, payload: dict[str, Any]) -> None:
    terminal_key = optional_str(payload.get("TerminalKey"))
    bank_order_id = optional_str(payload.get("OrderId"))
    bank_payment_id = optional_str(payload.get("PaymentId"))
    status_value = optional_str(payload.get("Status"))
    success_value = payload.get("Success") if isinstance(payload.get("Success"), bool) else None

    payment = await resolve_tbank_payment_for_update(
        db,
        bank_order_id=bank_order_id,
        bank_payment_id=bank_payment_id,
    )
    organization = payment.organization if payment is not None else await resolve_tbank_organization(db, terminal_key)

    token_valid = False
    error_info = None
    if organization is None:
        error_info = {"message": "Organization was not found for T-Bank webhook"}
    else:
        try:
            credentials = get_tbank_credentials(organization)
            token_valid = verify_tbank_token(payload, credentials.password)
            if not token_valid:
                error_info = {"message": "Invalid T-Bank webhook token"}
        except HTTPException as exc:
            error_info = {"message": str(exc.detail)}

    order_id = payment.order_id if payment is not None else parse_uuid(bank_order_id)
    event = TBankPaymentEvent(
        payment_id=payment.id if payment is not None else None,
        order_id=order_id,
        terminal_key=terminal_key,
        bank_order_id=bank_order_id,
        bank_payment_id=bank_payment_id,
        event_type="webhook",
        status=status_value,
        success=success_value,
        token_valid=token_valid,
        processed=False,
        raw_payload=payload,
        error_info=error_info,
    )
    db.add(event)

    if not token_valid or payment is None:
        await db.commit()
        logger.warning(
            "Ignored T-Bank webhook: bank_order_id=%s bank_payment_id=%s token_valid=%s payment_found=%s error=%s",
            bank_order_id,
            bank_payment_id,
            token_valid,
            payment is not None,
            error_info,
        )
        return

    previous_payment_status = payment.status
    next_status = map_tbank_status(status_value)
    payment.last_notification = payload
    if bank_payment_id and not payment.bank_payment_id:
        payment.bank_payment_id = bank_payment_id

    order = payment.order
    payment.status = next_status
    order.payment_status = resolve_order_payment_status(order, next_status)
    order.payment_error_info = None
    event.processed = True

    if order.payment_status == "paid":
        payment.paid_at = payment.paid_at or utcnow()
        order.creation_status = order.creation_status if order.iiko_order_id else "PaymentConfirmed"
    elif order.payment_status in {"payment_failed", "payment_cancelled", "payment_expired"}:
        payment.failed_at = payment.failed_at or utcnow()
        order.creation_status = "PaymentFailed"

    await db.commit()
    if previous_payment_status != payment.status:
        logger.info(
            "T-Bank webhook updated payment: order_id=%s payment_id=%s status=%s order_payment_status=%s",
            order.id,
            payment.id,
            payment.status,
            order.payment_status,
        )

    if order.payment_status == "paid":
        try:
            await dispatch_paid_order_to_iiko(db, order.id)
        except Exception:
            logger.exception("Failed to dispatch paid order %s to iiko after T-Bank webhook", order.id)


async def resolve_tbank_payment_for_update(
    db: AsyncSession,
    *,
    bank_order_id: str | None,
    bank_payment_id: str | None,
) -> TBankPayment | None:
    statement = (
        select(TBankPayment)
        .options(selectinload(TBankPayment.order), selectinload(TBankPayment.organization))
        .with_for_update()
    )
    if bank_payment_id:
        payment = await db.scalar(statement.where(TBankPayment.bank_payment_id == bank_payment_id))
        if payment:
            return payment

    if bank_order_id:
        return await db.scalar(statement.where(TBankPayment.bank_order_id == bank_order_id))

    return None


async def resolve_tbank_organization(db: AsyncSession, terminal_key: str | None) -> Organization | None:
    if not terminal_key:
        return None

    organization = await db.scalar(select(Organization).where(Organization.tbank_terminal_key == terminal_key))
    if organization:
        return organization

    if settings.tbank_default_terminal_key == terminal_key:
        return await db.scalar(select(Organization).order_by(Organization.created_at).limit(1))

    return None


async def dispatch_paid_order_to_iiko(db: AsyncSession, order_id) -> bool:
    local_order = await db.scalar(
        select(Order)
        .options(selectinload(Order.organization))
        .where(Order.id == order_id)
        .with_for_update()
    )
    if local_order is None or local_order.payment_status != "paid":
        return False
    if local_order.iiko_order_id:
        return True
    if (
        local_order.creation_status == "IikoCreateInProgress"
        and local_order.updated_at
        and (utcnow() - local_order.updated_at).total_seconds() < IIKO_DISPATCH_IN_PROGRESS_TIMEOUT_SECONDS
    ):
        return False

    local_order.creation_status = "IikoCreateInProgress"
    await db.commit()

    organization = local_order.organization
    access_token = await get_order_access_token(db, organization)
    terminal_group_id = local_order.terminal_group_id
    if not terminal_group_id:
        if local_order.iiko_organization_id != organization.iiko_organization_id:
            local_order.creation_status = "IikoCreateFailed"
            local_order.error_info = {"message": "Order belongs to a previous iiko organization configuration"}
            await db.commit()
            return False
        terminal_group_id = await get_order_terminal_group_id(access_token, organization)
    order_body = sanitize_iiko_order_payload(local_order.iiko_order_payload)
    if order_body != local_order.iiko_order_payload:
        local_order.iiko_order_payload = order_body

    try:
        data = await request_iiko_json(
            "/api/1/deliveries/create",
            access_token,
            json_body={
                "organizationId": local_order.iiko_organization_id,
                "terminalGroupId": terminal_group_id,
                "order": order_body,
            },
        )
    except IikoTerminalError as exc:
        local_order.creation_status = "IikoCreateFailed"
        local_order.error_info = {"message": str(exc)}
        await db.commit()
        logger.warning("iiko order creation failed for order %s: %s", local_order.id, exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"iiko order creation failed: {exc}") from exc

    order_info = data.get("orderInfo")
    if not isinstance(order_info, dict):
        local_order.creation_status = "IikoCreateFailed"
        local_order.error_info = {"message": "iiko did not return orderInfo"}
        local_order.iiko_create_response = data
        await db.commit()
        logger.warning("iiko order creation returned invalid response for order %s", local_order.id)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "iiko did not return orderInfo")

    update_local_order_from_create_response(local_order, data, order_info)
    if local_order.iiko_order_id:
        await ensure_order_notification(db, local_order, "order_created")
    await db.commit()
    logger.info(
        "Paid order dispatched to iiko: order_id=%s public_number=%s iiko_order_id=%s creation_status=%s",
        local_order.id,
        local_order.public_number,
        local_order.iiko_order_id,
        local_order.creation_status,
    )
    return True


async def dispatch_paid_orders_once() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.scalars(
            select(Order.id)
            .join(Order.organization)
            .where(
                Order.payment_status == "paid",
                Order.iiko_order_id.is_(None),
                Order.iiko_organization_id == Organization.iiko_organization_id,
                Order.creation_status.in_(PAID_IIKO_RETRY_STATUSES),
            )
            .order_by(Order.updated_at)
            .limit(20)
        )
        order_ids = list(result)

        for order_id in order_ids:
            try:
                await dispatch_paid_order_to_iiko(db, order_id)
            except Exception:
                logger.exception("Failed to dispatch paid order %s to iiko", order_id)


async def run_iiko_order_dispatcher(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await dispatch_paid_orders_once()
        except Exception:
            logger.exception("Unexpected error while dispatching paid orders")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.iiko_order_dispatch_poll_seconds)
        except asyncio.TimeoutError:
            pass


async def sync_active_iiko_order_statuses_once() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.scalars(
            select(Order.id)
            .join(Order.organization)
            .where(
                Order.customer_id.is_not(None),
                Order.iiko_order_id.is_not(None),
                Order.iiko_organization_id == Organization.iiko_organization_id,
                or_(Order.order_status.is_(None), Order.order_status.not_in(FINAL_ORDER_STATUSES)),
            )
            .order_by(Order.updated_at)
            .limit(50)
        )
        order_ids = list(result)

        for order_id in order_ids:
            try:
                await get_iiko_order_status(
                    db,
                    order_id=str(order_id),
                    organization_id=None,
                    organization_slug=None,
                )
            except Exception:
                logger.exception("Failed to sync iiko status for order %s", order_id)


async def run_iiko_order_status_poller(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await sync_active_iiko_order_statuses_once()
        except Exception:
            logger.exception("Unexpected error while syncing iiko order statuses")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.iiko_order_status_poll_seconds)
        except asyncio.TimeoutError:
            pass


async def sync_pending_tbank_payments_once() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.scalars(
            select(TBankPayment.id)
            .where(
                TBankPayment.bank_payment_id.is_not(None),
                TBankPayment.status.not_in(FINAL_PAYMENT_STATUSES),
            )
            .order_by(TBankPayment.updated_at)
            .limit(20)
        )
        payment_ids = list(result)

        for payment_id in payment_ids:
            try:
                await sync_tbank_payment_state(db, payment_id)
            except Exception:
                logger.exception("Failed to sync T-Bank payment %s state", payment_id)

        await expire_overdue_unpaid_orders(db)


async def sync_tbank_payment_state(db: AsyncSession, payment_id) -> None:
    payment = await db.scalar(
        select(TBankPayment)
        .options(selectinload(TBankPayment.organization))
        .where(TBankPayment.id == payment_id)
    )
    if payment is None or payment.status in FINAL_PAYMENT_STATUSES or not payment.bank_payment_id:
        return

    try:
        credentials = get_tbank_credentials(payment.organization)
        state = await get_tbank_payment_state(credentials=credentials, bank_payment_id=payment.bank_payment_id)
    except (TBankError, HTTPException) as exc:
        db.add(
            TBankPaymentEvent(
                payment_id=payment.id,
                order_id=payment.order_id,
                terminal_key=payment.terminal_key,
                bank_order_id=payment.bank_order_id,
                bank_payment_id=payment.bank_payment_id,
                event_type="get_state",
                status=payment.status,
                success=False,
                token_valid=None,
                processed=False,
                raw_payload={},
                error_info={"message": str(exc)},
            )
        )
        await db.commit()
        return

    payment = await db.scalar(
        select(TBankPayment)
        .options(selectinload(TBankPayment.order))
        .where(TBankPayment.id == payment_id)
        .with_for_update()
    )
    if payment is None or payment.status in FINAL_PAYMENT_STATUSES:
        return

    next_status = map_tbank_status(state.get("Status"))
    event = TBankPaymentEvent(
        payment_id=payment.id,
        order_id=payment.order_id,
        terminal_key=payment.terminal_key,
        bank_order_id=payment.bank_order_id,
        bank_payment_id=payment.bank_payment_id,
        event_type="get_state",
        status=optional_str(state.get("Status")),
        success=state.get("Success") if isinstance(state.get("Success"), bool) else None,
        token_valid=None,
        processed=True,
        raw_payload=state,
    )
    db.add(event)

    previous_payment_status = payment.status
    payment.last_notification = state
    order = payment.order
    payment.status = next_status
    order.payment_status = resolve_order_payment_status(order, next_status)
    order.payment_error_info = None

    if order.payment_status == "paid":
        payment.paid_at = payment.paid_at or utcnow()
        order.creation_status = order.creation_status if order.iiko_order_id else "PaymentConfirmed"
    elif order.payment_status in {"payment_failed", "payment_cancelled", "payment_expired"}:
        payment.failed_at = payment.failed_at or utcnow()
        order.creation_status = "PaymentFailed"

    await db.commit()
    if previous_payment_status != payment.status:
        logger.info(
            "T-Bank poll updated payment: order_id=%s payment_id=%s status=%s order_payment_status=%s",
            order.id,
            payment.id,
            payment.status,
            order.payment_status,
        )

    if order.payment_status == "paid":
        await dispatch_paid_order_to_iiko(db, order.id)


async def expire_customer_overdue_unpaid_orders(db: AsyncSession, customer: Customer) -> None:
    await expire_overdue_unpaid_orders(db, customer_id=customer.id)


async def expire_overdue_unpaid_orders(db: AsyncSession, *, customer_id=None, limit: int = 100) -> int:
    statement = (
        select(Order)
        .options(selectinload(Order.payments))
        .where(
            Order.payment_status.in_(ACTIVE_PAYMENT_STATUSES),
            Order.iiko_order_id.is_(None),
        )
        .order_by(Order.created_at)
        .limit(limit)
    )
    if customer_id is not None:
        statement = statement.where(Order.customer_id == customer_id)

    result = await db.scalars(statement)
    orders = list(result)

    expired_count = 0
    now = utcnow()
    for order in orders:
        if not is_order_payment_overdue(order, now=now):
            continue

        expire_unpaid_order(order, now=now)
        expired_count += 1

    if expired_count:
        await db.commit()
        logger.info("Expired overdue unpaid orders: count=%s", expired_count)

    return expired_count


def is_order_payment_overdue(order: Order, *, now: datetime | None = None) -> bool:
    deadline = get_order_payment_deadline(order)
    if deadline is None:
        return False

    return (now or utcnow()) >= deadline


def get_order_payment_deadline(order: Order) -> datetime | None:
    if order.complete_before is not None:
        return normalize_order_datetime(order.complete_before) - timedelta(
            minutes=settings.order_unpaid_payment_deadline_minutes
        )

    return normalize_order_datetime(order.created_at) + timedelta(minutes=settings.order_unpaid_payment_ttl_minutes)


def expire_unpaid_order(order: Order, *, now: datetime) -> None:
    order.payment_status = "payment_expired"
    order.payment_error_info = {
        "message": "Payment was not completed before the order payment deadline",
        "reason": "order_payment_deadline_expired",
    }
    order.creation_status = "PaymentExpired"

    for payment in order.payments:
        if payment.status in FINAL_PAYMENT_STATUSES:
            continue
        payment.is_active = False
        payment.error_info = order.payment_error_info


def resolve_order_payment_status(order: Order, next_status: str) -> str:
    if next_status == "paid":
        return next_status
    if next_status in ACTIVE_PAYMENT_STATUSES and is_order_payment_overdue(order):
        expire_unpaid_order(order, now=utcnow())
        return "payment_expired"
    return next_status


async def run_tbank_payment_state_poller(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await sync_pending_tbank_payments_once()
        except Exception:
            logger.exception("Unexpected error while syncing T-Bank payment states")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.tbank_state_poll_seconds)
        except asyncio.TimeoutError:
            pass


async def resolve_order_organization(db: AsyncSession, payload: OrderCreateIn) -> Organization:
    statement = select(Organization).options(
        selectinload(Organization.iiko_menu_snapshot),
        selectinload(Organization.working_hours),
    )

    if payload.order_type == "pickup":
        if payload.organization_id is not None:
            statement = statement.where(Organization.id == payload.organization_id)
        elif payload.organization_slug is not None:
            statement = statement.where(Organization.slug == payload.organization_slug.strip().lower())

        organization = await db.scalar(statement)
        if not organization:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
        if not organization.accepts_pickup:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Organization does not accept pickup orders")
        ensure_order_organization_configured(organization)
        ensure_organization_accepts_orders_now(organization)
        return organization

    organization = await db.scalar(
        statement.where(
            Organization.accepts_delivery.is_(True),
            Organization.is_default_delivery.is_(True),
        ).limit(1)
    )
    if not organization:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Default delivery organization is not configured")

    ensure_order_organization_configured(organization)
    ensure_organization_accepts_orders_now(organization)
    return organization


async def resolve_delivery_calculation(
    db: AsyncSession,
    organization: Organization,
    payload: OrderCreateIn,
) -> dict[str, Any] | None:
    if payload.order_type != "delivery":
        return None
    if payload.delivery_point is None or payload.delivery_point.coordinates is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "deliveryPoint.coordinates is required for delivery")

    coordinates = payload.delivery_point.coordinates
    return await ensure_delivery_available_for_coordinates(
        db,
        organization=organization,
        latitude=coordinates.latitude,
        longitude=coordinates.longitude,
    )


async def create_local_order(
    db: AsyncSession,
    *,
    organization: Organization,
    payload: OrderCreateIn,
    customer: Customer | None,
    order_phone: str,
    terminal_group_id: str,
    order_type: dict[str, str],
    order_body: dict[str, Any],
    amount_kopecks: int,
    delivery_calculation: dict[str, Any] | None = None,
) -> Order:
    public_number = await generate_public_order_number(db)
    order = Order(
        public_number=public_number,
        organization_id=organization.id,
        customer_id=customer.id if customer is not None else None,
        organization_slug=organization.slug,
        iiko_organization_id=organization.iiko_organization_id,
        terminal_group_id=terminal_group_id,
        order_type=payload.order_type,
        iiko_order_type_id=order_type["id"],
        iiko_order_service_type=order_type["orderServiceType"],
        phone=order_phone,
        comment=payload.comment,
        complete_before=payload.complete_before,
        guests_count=payload.guests_count,
        delivery_point=build_local_delivery_point(payload, delivery_calculation),
        items=list(order_body.get("items") or [item.model_dump(by_alias=True) for item in payload.items]),
        iiko_order_payload=order_body,
        payment_status="payment_pending",
        payment_amount_kopecks=amount_kopecks,
        total_sum=amount_kopecks / 100,
        creation_status="PaymentPending",
    )
    db.add(order)
    await db.flush()
    iiko_order_payload = {
        **order_body,
        "externalNumber": order.public_number,
    }
    if organization.iiko_online_payment_type_id:
        iiko_order_payload["payments"] = [build_iiko_online_payment(organization, amount_kopecks)]
    order.iiko_order_payload = iiko_order_payload
    await db.commit()
    await db.refresh(order)
    return order


async def generate_public_order_number(db: AsyncSession) -> str:
    next_number = await db.scalar(text("SELECT nextval('order_public_number_seq')"))
    return encode_public_order_number(int(next_number))


def encode_public_order_number(value: int) -> str:
    if value < 1:
        raise ValueError("Public order number value must be positive")

    base = len(PUBLIC_ORDER_NUMBER_ALPHABET)
    encoded = ""
    while value:
        value, remainder = divmod(value, base)
        encoded = PUBLIC_ORDER_NUMBER_ALPHABET[remainder] + encoded

    return encoded.rjust(PUBLIC_ORDER_NUMBER_MIN_LENGTH, "0")


def normalize_public_order_number(value: Any) -> str:
    return str(value).strip().upper().replace("-", "").replace(" ", "")


def build_local_delivery_point(
    payload: OrderCreateIn,
    delivery_calculation: dict[str, Any] | None,
) -> dict | None:
    if payload.delivery_point is None:
        return None

    delivery_point = payload.delivery_point.model_dump(by_alias=True)
    if delivery_calculation is not None:
        delivery_point["deliveryCalculation"] = serialize_delivery_calculation(delivery_calculation)
    return delivery_point


def serialize_delivery_calculation(delivery_calculation: dict[str, Any] | None) -> dict[str, Any] | None:
    if delivery_calculation is None:
        return None

    zone = delivery_calculation.get("zone")
    return {
        "available": delivery_calculation["available"],
        "reason": delivery_calculation["reason"],
        "distanceKm": delivery_calculation["distance_km"],
        "price": delivery_calculation["price"],
        "zone": {
            "id": str(zone.id),
            "distanceFromKm": float(zone.distance_from_km),
            "distanceToKm": float(zone.distance_to_km) if zone.distance_to_km is not None else None,
            "price": zone.price,
        }
        if zone is not None
        else None,
        "address": delivery_calculation.get("address"),
    }


async def resolve_local_status_order(db: AsyncSession, order_id: str, *, customer: Customer | None = None) -> Order | None:
    try:
        parsed_order_id = UUID(order_id)
    except ValueError:
        parsed_order_id = None

    statement = (
        select(Order)
        .options(selectinload(Order.organization))
    )
    if parsed_order_id is None:
        statement = statement.where(Order.public_number == normalize_public_order_number(order_id))
    else:
        statement = statement.where(Order.id == parsed_order_id)
    if customer is not None:
        statement = statement.where(Order.customer_id == customer.id)

    return await db.scalar(statement)


def update_local_order_from_create_response(
    local_order: Order,
    data: dict[str, Any],
    order_info: dict[str, Any],
) -> None:
    local_order.iiko_correlation_id = optional_str(data.get("correlationId"))
    local_order.iiko_order_id = optional_str(order_info.get("id"))
    local_order.iiko_pos_id = optional_str(order_info.get("posId"))
    local_order.iiko_external_number = optional_str(order_info.get("externalNumber"))
    local_order.creation_status = optional_str(order_info.get("creationStatus"))
    local_order.error_info = normalize_error_info(order_info.get("errorInfo"))
    local_order.iiko_create_response = data


def update_local_order_from_status_response(
    local_order: Order,
    data: dict[str, Any],
    order_info: dict[str, Any],
    order: dict[str, Any],
    notification_event: str | None,
) -> None:
    local_order.iiko_correlation_id = optional_str(data.get("correlationId")) or local_order.iiko_correlation_id
    local_order.creation_status = optional_str(order_info.get("creationStatus"))
    local_order.order_status = optional_str(order.get("status"))
    local_order.notification_event = notification_event
    local_order.total_sum = parse_float(order.get("sum"))
    local_order.error_info = normalize_error_info(order_info.get("errorInfo"))
    local_order.iiko_status_response = data


async def resolve_status_organization(
    db: AsyncSession,
    *,
    organization_id,
    organization_slug: str | None,
) -> Organization:
    if organization_id is None and organization_slug is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "organizationId or organizationSlug is required")

    statement = select(Organization)
    if organization_id is not None:
        statement = statement.where(Organization.id == organization_id)
    else:
        statement = statement.where(Organization.slug == organization_slug.strip().lower())

    organization = await db.scalar(statement)
    if not organization:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")

    ensure_order_organization_configured(organization)
    return organization


def ensure_order_organization_configured(organization: Organization) -> None:
    if not organization.iiko_organization_id:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Organization iiko id is not configured")
    if not organization.iiko_api_login:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Organization iiko apiLogin is not configured")


def resolve_tbank_notification_url() -> str:
    notification_url = settings.resolved_tbank_notification_url
    if not notification_url:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "T-Bank notification URL is not configured")
    return notification_url


async def get_order_access_token(db: AsyncSession, organization: Organization) -> str:
    try:
        return await get_valid_token(db, organization.id)
    except IikoAuthorizationError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "iiko authorization is not available") from exc


async def get_order_terminal_group_id(access_token: str, organization: Organization) -> str:
    try:
        return await get_alive_iiko_terminal_group_id(access_token, organization.iiko_organization_id)
    except IikoTerminalError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "iiko terminal is not available") from exc


async def get_iiko_order_type(access_token: str, organization: Organization, order_type: OrderKind) -> dict[str, str]:
    service_types = DELIVERY_ORDER_SERVICE_TYPES if order_type == "delivery" else PICKUP_ORDER_SERVICE_TYPES

    try:
        data = await request_iiko_json(
            "/api/1/deliveries/order_types",
            access_token,
            json_body={"organizationIds": [organization.iiko_organization_id]},
        )
    except IikoTerminalError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"iiko order types request failed: {exc}") from exc

    order_types = data.get("orderTypes")
    if not isinstance(order_types, list):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "iiko did not return orderTypes")

    candidates: list[dict[str, Any]] = []
    for organization_order_types in order_types:
        if not isinstance(organization_order_types, dict):
            continue
        if organization_order_types.get("organizationId") != organization.iiko_organization_id:
            continue
        items = organization_order_types.get("items")
        if isinstance(items, list):
            candidates.extend(item for item in items if isinstance(item, dict))

    candidates = [
        item
        for item in candidates
        if item.get("isDeleted") is not True and item.get("orderServiceType") in service_types and item.get("id")
    ]
    if not candidates:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"iiko {order_type} order type is not configured")

    selected = next((item for item in candidates if item.get("isDefault") is True), candidates[0])
    return {
        "id": str(selected["id"]),
        "orderServiceType": str(selected.get("orderServiceType") or ""),
    }


def build_local_order_status(local_order: Order) -> dict[str, Any]:
    return {
        "id": local_order.id,
        "public_number": local_order.public_number,
        "correlation_id": local_order.iiko_correlation_id,
        "organization_id": local_order.organization_id,
        "organization_slug": local_order.organization_slug,
        "iiko_organization_id": local_order.iiko_organization_id,
        "order_type": local_order.order_type,
        "iiko_order_id": local_order.iiko_order_id,
        "creation_status": local_order.creation_status,
        "order_status": local_order.order_status,
        "payment_status": local_order.payment_status,
        "payment_amount_kopecks": local_order.payment_amount_kopecks,
        "number": None,
        "sum": float(local_order.total_sum) if local_order.total_sum is not None else None,
        "complete_before": local_order.complete_before.isoformat() if local_order.complete_before else None,
        "comment": local_order.comment,
        "notification_event": local_order.notification_event,
        "should_notify_customer": False,
        "error_info": local_order.error_info or local_order.payment_error_info,
    }


def build_iiko_order_body(
    organization: Organization,
    payload: OrderCreateIn,
    order_type_id: str,
    *,
    order_phone: str,
) -> dict[str, Any]:
    order: dict[str, Any] = {
        "phone": order_phone,
        "orderTypeId": order_type_id,
        "items": [build_iiko_item(organization, item) for item in payload.items],
        "guests": {"count": payload.guests_count, "splitBetweenPersons": False},
    }

    if payload.comment:
        order["comment"] = payload.comment
    if payload.complete_before is not None:
        order["completeBefore"] = format_iiko_datetime(payload.complete_before)
    if payload.order_type == "delivery" and payload.delivery_point is not None:
        order["deliveryPoint"] = build_delivery_point(payload.delivery_point)

    return order


def build_iiko_online_payment(organization: Organization, amount_kopecks: int) -> dict[str, Any]:
    return {
        "paymentTypeKind": organization.iiko_online_payment_type_kind,
        "paymentTypeId": organization.iiko_online_payment_type_id,
        "sum": amount_kopecks / 100,
        "isProcessedExternally": True,
    }


def calculate_order_amount_kopecks(
    order_body: dict[str, Any],
    *,
    delivery_calculation: dict[str, Any] | None = None,
) -> int:
    total = Decimal("0")
    items = order_body.get("items")
    if not isinstance(items, list) or not items:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Order has no items")

    for item in items:
        if not isinstance(item, dict):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid order item")

        item_amount = decimal_from_value(item.get("amount"), "item amount")
        item_price = decimal_from_value(item.get("price"), "item price")
        total += item_price * item_amount

        modifiers = item.get("modifiers") or []
        if not isinstance(modifiers, list):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid order modifiers")
        for modifier in modifiers:
            if not isinstance(modifier, dict):
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid order modifier")
            modifier_amount = decimal_from_value(modifier.get("amount"), "modifier amount")
            modifier_price = decimal_from_value(modifier.get("price"), "modifier price")
            total += modifier_price * modifier_amount

    if total <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Order total must be greater than zero")

    if delivery_calculation is not None:
        total += decimal_from_value(delivery_calculation.get("price"), "delivery price")

    return int((total * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def decimal_from_value(value: Any, field_name: str) -> Decimal:
    if value is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Missing {field_name}")
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid {field_name}") from exc
    if result < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid {field_name}")
    return result


def resolve_order_phone(payload: OrderCreateIn, customer: Customer | None) -> str:
    if customer is None:
        if payload.phone is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Phone is required")
        return payload.phone

    if payload.phone is not None:
        try:
            payload_phone = normalize_phone(payload.phone)
        except InvalidPhoneNumberError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid phone number")
        if payload_phone != customer.phone:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Order phone must match authenticated customer")

    return customer.phone


def build_iiko_item(organization: Organization, item: OrderItemIn) -> dict[str, Any]:
    menu_item = find_menu_item(organization, item.product_id, item.product_size_id)
    price = menu_item["price"] if menu_item else item.price

    if price is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Price for product {item.product_id} was not found in menu",
        )

    result: dict[str, Any] = {
        "productId": item.product_id,
        "price": float(price),
        "type": "Product",
        "amount": item.amount,
    }

    product_size_id = item.product_size_id or (menu_item or {}).get("productSizeId")
    if product_size_id:
        result["productSizeId"] = product_size_id
    if item.comment:
        result["comment"] = item.comment

    modifiers = build_iiko_modifiers(organization, item, menu_item)
    if modifiers:
        result["modifiers"] = modifiers

    return result


def find_menu_item(
    organization: Organization,
    product_id: str,
    product_size_id: str | None,
) -> dict[str, Any] | None:
    snapshot = organization.iiko_menu_snapshot
    raw_menu = snapshot.raw_menu if snapshot and isinstance(snapshot.raw_menu, dict) else None
    if not raw_menu or not organization.iiko_organization_id:
        return None

    for category in raw_menu.get("itemCategories") or []:
        if not isinstance(category, dict):
            continue
        for item in category.get("items") or []:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("itemId") or item.get("id") or "")
            if item_id != product_id:
                continue

            item_size = select_menu_item_size(item, organization.iiko_organization_id, product_size_id)
            if item_size is None:
                return None
            price = select_menu_price(item_size, organization.iiko_organization_id)
            if price is None:
                return None

            return {
                "price": price,
                "productSizeId": optional_str(item_size.get("sizeId")),
                "itemSize": item_size,
            }

    return None


def build_iiko_modifiers(
    organization: Organization,
    item: OrderItemIn,
    menu_item: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not item.modifiers and (not menu_item or not organization.iiko_organization_id):
        return []

    if not menu_item or not organization.iiko_organization_id:
        return build_unresolved_iiko_modifiers(item)

    item_size = menu_item.get("itemSize")
    if not isinstance(item_size, dict):
        return build_unresolved_iiko_modifiers(item)

    groups = build_menu_modifier_groups(item_size, organization.iiko_organization_id)
    if not groups:
        if not item.modifiers:
            return []
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Product {item.product_id} does not support modifiers",
        )

    resolved_modifiers = []
    group_totals = {group_id: 0.0 for group_id in groups}
    child_totals: dict[tuple[str, str], float] = {}

    for modifier in item.modifiers:
        resolved = resolve_iiko_modifier(modifier, groups)
        group_id = resolved.pop("_groupId")
        product_id = resolved["productId"]
        amount = float(resolved["amount"])
        child_key = (group_id, product_id)
        child_totals[child_key] = child_totals.get(child_key, 0.0) + amount
        resolved_modifiers.append(resolved)

    for (group_id, product_id), amount in child_totals.items():
        modifier_info = groups[group_id]["items"][product_id]
        if groups[group_id]["child_modifiers_have_min_max_restrictions"]:
            validate_modifier_quantity(
                amount,
                modifier_info["restrictions"],
                f"Modifier {product_id}",
            )
        if groups[group_id]["child_modifiers_have_min_max_restrictions"]:
            group_totals[group_id] = group_totals.get(group_id, 0.0) + 1
        else:
            group_totals[group_id] = group_totals.get(group_id, 0.0) + amount

    for group_id, group_info in groups.items():
        validate_modifier_group_quantity(
            group_totals.get(group_id, 0.0),
            group_info,
            f"Modifier group {group_id}",
        )

    return resolved_modifiers


def build_unresolved_iiko_modifiers(item: OrderItemIn) -> list[dict[str, Any]]:
    modifiers = []
    for modifier in item.modifiers:
        if modifier.price is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Price for modifier {modifier.product_id} was not found in menu",
            )
        modifiers.append(
            {
                key: value
                for key, value in {
                    "productId": modifier.product_id,
                    "productGroupId": as_iiko_guid(modifier.product_group_id),
                    "amount": modifier.amount,
                    "price": modifier.price,
                }.items()
                if value is not None
            }
        )
    return modifiers


def build_menu_modifier_groups(item_size: dict[str, Any], iiko_organization_id: str) -> dict[str, dict[str, Any]]:
    groups = {}
    for group in item_size.get("itemModifierGroups") or []:
        if not isinstance(group, dict) or group.get("isHidden") or group.get("isDeleted"):
            continue

        group_id = optional_str(group.get("itemGroupId") or group.get("id") or group.get("sku") or group.get("name"))
        if not group_id:
            continue

        items = {}
        for modifier in group.get("items") or []:
            if not isinstance(modifier, dict) or modifier.get("isHidden") or modifier.get("isDeleted"):
                continue
            product_id = optional_str(modifier.get("itemId") or modifier.get("id"))
            if not product_id:
                continue
            price = select_menu_price(modifier, iiko_organization_id)
            items[product_id] = {
                "price": price if price is not None else 0,
                "restrictions": parse_iiko_modifier_restrictions(modifier.get("restrictions")),
            }

        if items:
            restrictions = parse_iiko_modifier_restrictions(group.get("restrictions"))
            child_modifiers_have_min_max_restrictions = bool(
                group.get("childModifiersHaveMinMaxRestrictions")
            )
            groups[group_id] = {
                "required": is_iiko_modifier_group_required(
                    group,
                    restrictions,
                    child_modifiers_have_min_max_restrictions,
                ),
                "restrictions": restrictions,
                "child_modifiers_have_min_max_restrictions": child_modifiers_have_min_max_restrictions,
                "items": items,
            }

    return groups


def resolve_iiko_modifier(
    modifier: OrderModifierIn,
    groups: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if modifier.product_group_id:
        group = groups.get(modifier.product_group_id)
        if not group or modifier.product_id not in group["items"]:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Modifier {modifier.product_id} is not available in group {modifier.product_group_id}",
            )
        group_id = modifier.product_group_id
        modifier_info = group["items"][modifier.product_id]
    else:
        matches = [
            (group_id, group["items"][modifier.product_id])
            for group_id, group in groups.items()
            if modifier.product_id in group["items"]
        ]
        if not matches:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Modifier {modifier.product_id} is not available for this product",
            )
        if len(matches) > 1:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"productGroupId is required for modifier {modifier.product_id}",
            )
        group_id, modifier_info = matches[0]

    result = {
        "productId": modifier.product_id,
        "amount": modifier.amount,
        "price": float(modifier_info["price"]),
        "_groupId": group_id,
    }
    iiko_group_id = as_iiko_guid(group_id)
    if iiko_group_id is not None:
        result["productGroupId"] = iiko_group_id

    return result


def sanitize_iiko_order_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}

    order = dict(payload)
    items = order.get("items")
    if isinstance(items, list):
        order["items"] = [sanitize_iiko_order_item(item) for item in items]

    return order


def sanitize_iiko_order_item(item: Any) -> Any:
    if not isinstance(item, dict):
        return item

    result = dict(item)
    modifiers = result.get("modifiers")
    if isinstance(modifiers, list):
        result["modifiers"] = [sanitize_iiko_modifier(modifier) for modifier in modifiers]

    return result


def sanitize_iiko_modifier(modifier: Any) -> Any:
    if not isinstance(modifier, dict):
        return modifier

    result = dict(modifier)
    product_group_id = as_iiko_guid(optional_str(result.get("productGroupId")))
    if product_group_id is None:
        result.pop("productGroupId", None)
    else:
        result["productGroupId"] = product_group_id

    return result


def is_iiko_modifier_group_required(
    group: dict[str, Any],
    restrictions: dict[str, float | None],
    child_modifiers_have_min_max_restrictions: bool,
) -> bool:
    for key in ("required", "isRequired"):
        value = group.get(key)
        if isinstance(value, bool):
            return value

    return bool(restrictions["min_quantity"] and restrictions["min_quantity"] > 0)


def validate_modifier_quantity(amount: float, restrictions: dict[str, float | None], label: str) -> None:
    min_quantity = restrictions["min_quantity"]
    max_quantity = restrictions["max_quantity"]
    by_default = restrictions.get("by_default") or 0

    if amount < min_quantity:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{label} requires at least {min_quantity:g}",
        )
    is_default_included_amount = (
        min_quantity == 0
        and max_quantity == 0
        and by_default > 0
        and amount <= by_default
    )
    if max_quantity is not None and amount > max_quantity and not is_default_included_amount:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{label} allows at most {max_quantity:g}",
        )


def validate_modifier_group_quantity(amount: float, group_info: dict[str, Any], label: str) -> None:
    restrictions = dict(group_info["restrictions"])
    if not group_info["required"]:
        restrictions["min_quantity"] = 0

    validate_modifier_quantity(amount, restrictions, label)


def parse_iiko_modifier_restrictions(value: Any) -> dict[str, float | None]:
    restrictions = value if isinstance(value, dict) else {}
    return {
        "min_quantity": parse_float(restrictions.get("minQuantity")) or 0,
        "max_quantity": parse_float(restrictions.get("maxQuantity")),
        "by_default": parse_float(restrictions.get("byDefault")) or 0,
    }


def select_menu_item_size(
    item: dict[str, Any],
    iiko_organization_id: str,
    product_size_id: str | None,
) -> dict[str, Any] | None:
    sizes = [size for size in item.get("itemSizes") or [] if isinstance(size, dict) and not size.get("isHidden")]
    if not sizes:
        return None

    if product_size_id is not None:
        return next((size for size in sizes if str(size.get("sizeId")) == product_size_id), None)

    default_sizes = [size for size in sizes if size.get("isDefault")]
    for size in [*default_sizes, *sizes]:
        if select_menu_price(size, iiko_organization_id) is not None:
            return size

    return None


def select_menu_price(item_size: dict[str, Any], iiko_organization_id: str) -> float | None:
    prices = [price for price in item_size.get("prices") or [] if isinstance(price, dict)]
    for price in prices:
        if optional_str(price.get("organizationId")) == iiko_organization_id:
            return parse_float(price.get("price"))

    if len(prices) == 1 and not optional_str(prices[0].get("organizationId")):
        return parse_float(prices[0].get("price"))

    return None


def build_delivery_point(delivery_point: DeliveryPointIn) -> dict[str, Any]:
    address = delivery_point.address
    result: dict[str, Any] = {
        "address": {
            "city": address.city,
            "street": {"name": address.street, "city": address.city},
            "house": address.house,
        }
    }

    optional_address_fields = {
        "index": address.index,
        "building": address.building,
        "flat": address.flat,
        "entrance": address.entrance,
        "floor": address.floor,
        "doorphone": address.doorphone,
        "regionId": address.region_id,
    }
    result["address"].update({key: value for key, value in optional_address_fields.items() if value is not None})

    if delivery_point.coordinates is not None:
        result["coordinates"] = {
            "latitude": delivery_point.coordinates.latitude,
            "longitude": delivery_point.coordinates.longitude,
        }
    if delivery_point.comment:
        result["comment"] = delivery_point.comment
    if delivery_point.external_cartography_id:
        result["externalCartographyId"] = delivery_point.external_cartography_id

    return result


def format_iiko_datetime(value: datetime) -> str:
    timezone = get_iiko_terminal_timezone()
    if value.tzinfo is not None:
        value = value.astimezone(timezone).replace(tzinfo=None)

    return value.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def resolve_payment_redirect_due_date(complete_before: datetime | None) -> str | None:
    deadline = resolve_new_order_payment_deadline(complete_before)
    min_deadline = utcnow() + timedelta(seconds=MIN_TBANK_REDIRECT_DUE_SECONDS)
    if deadline < min_deadline:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Order payment deadline is too close to completeBefore",
        )

    return deadline.isoformat(timespec="seconds")


def resolve_new_order_payment_deadline(complete_before: datetime | None) -> datetime:
    if complete_before is None:
        return utcnow() + timedelta(minutes=settings.order_unpaid_payment_ttl_minutes)

    return normalize_order_datetime(complete_before) - timedelta(
        minutes=settings.order_unpaid_payment_deadline_minutes
    )


def normalize_order_datetime(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc)
    return value.replace(tzinfo=get_iiko_terminal_timezone()).astimezone(timezone.utc)


def get_iiko_terminal_timezone() -> ZoneInfo | timezone:
    try:
        return ZoneInfo(settings.iiko_terminal_timezone)
    except ZoneInfoNotFoundError:
        return timezone.utc


def detect_order_kind(order: dict[str, Any]) -> OrderKind | None:
    order_type = order.get("orderType")
    if not isinstance(order_type, dict):
        return None

    service_type = order_type.get("orderServiceType")
    if service_type in DELIVERY_ORDER_SERVICE_TYPES:
        return "delivery"
    if service_type in PICKUP_ORDER_SERVICE_TYPES:
        return "pickup"

    return None


def detect_notification_event(order_type: OrderKind | None, order_status: Any) -> str | None:
    if not isinstance(order_status, str):
        return None

    if order_type == "pickup" and order_status in PICKUP_READY_STATUSES:
        return "pickup_ready"
    if order_type == "delivery" and order_status in DELIVERY_ON_WAY_STATUSES:
        return "delivery_on_way"
    if order_type == "delivery" and order_status in DELIVERY_DELIVERED_STATUSES:
        return "delivery_delivered"

    return None


def normalize_error_info(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def parse_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def optional_str(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def as_iiko_guid(value: str | None) -> str | None:
    parsed = parse_uuid(value)
    return str(parsed) if parsed is not None else None


def parse_uuid(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None
