from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.base import utcnow
from app.models.customer import Customer
from app.models.order import Order, TBankPayment, TBankPaymentEvent
from app.models.organization import Organization
from app.schemas.order import DeliveryPointIn, OrderCreateIn, OrderItemIn, OrderKind
from app.services.availability import ensure_organization_accepts_orders_now
from app.services.iiko import (
    IikoAuthorizationError,
    IikoTerminalError,
    get_alive_iiko_terminal_group_id,
    get_valid_token,
    request_iiko_json,
)
from app.services.otp import InvalidPhoneNumberError, normalize_phone
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


async def create_order_payment(
    db: AsyncSession,
    payload: OrderCreateIn,
    customer: Customer | None = None,
) -> dict[str, Any]:
    order_phone = resolve_order_phone(payload, customer)
    organization = await resolve_order_organization(db, payload)
    access_token = await get_order_access_token(db, organization)
    terminal_group_id = await get_order_terminal_group_id(access_token, organization)
    order_type = await get_iiko_order_type(access_token, organization, payload.order_type)
    credentials = get_tbank_credentials(organization)
    notification_url = resolve_tbank_notification_url()
    order_body = build_iiko_order_body(organization, payload, order_type["id"], order_phone=order_phone)
    amount_kopecks = calculate_order_amount_kopecks(order_body)
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
            description=f"Order {local_order.id}",
            customer_key=str(customer.id) if customer is not None else None,
            notification_url=notification_url,
            success_url=payload.success_url or settings.tbank_success_url,
            fail_url=payload.fail_url or settings.tbank_fail_url,
            data={
                "localOrderId": str(local_order.id),
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

    return {
        "id": local_order.id,
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
    else:
        if customer is not None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
        iiko_order_id = order_id
        organization = await resolve_status_organization(
            db,
            organization_id=organization_id,
            organization_slug=organization_slug,
        )

    access_token = await get_order_access_token(db, organization)

    try:
        data = await request_iiko_json(
            "/api/1/deliveries/by_id",
            access_token,
            json_body={
                "organizationId": organization.iiko_organization_id,
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
        update_local_order_from_status_response(local_order, data, order_info, order, notification_event)
        await db.commit()
        await db.refresh(local_order)

    return {
        "id": local_order.id if local_order is not None else None,
        "correlation_id": data.get("correlationId"),
        "organization_id": organization.id,
        "organization_slug": organization.slug,
        "iiko_organization_id": organization.iiko_organization_id,
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


async def list_customer_current_orders(db: AsyncSession, customer: Customer, *, limit: int, offset: int) -> list[Order]:
    result = await db.scalars(
        select(Order)
        .options(selectinload(Order.organization))
        .where(
            Order.customer_id == customer.id,
            Order.creation_status != "Error",
            or_(Order.order_status.is_(None), Order.order_status.not_in(FINAL_ORDER_STATUSES)),
        )
        .order_by(Order.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result)


async def list_customer_order_history(db: AsyncSession, customer: Customer, *, limit: int, offset: int) -> list[Order]:
    result = await db.scalars(
        select(Order)
        .options(selectinload(Order.organization))
        .where(
            Order.customer_id == customer.id,
            or_(
                Order.creation_status == "Error",
                Order.payment_status.in_(("payment_failed", "payment_cancelled", "payment_expired")),
                Order.order_status.in_(FINAL_ORDER_STATUSES),
            ),
        )
        .order_by(Order.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result)


async def get_stored_order(db: AsyncSession, order_id) -> Order:
    order = await db.scalar(
        select(Order)
        .options(selectinload(Order.organization))
        .where(Order.id == order_id)
    )
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")

    return order


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
        return

    next_status = map_tbank_status(status_value)
    payment.last_notification = payload
    payment.status = next_status
    if bank_payment_id and not payment.bank_payment_id:
        payment.bank_payment_id = bank_payment_id

    order = payment.order
    order.payment_status = next_status
    order.payment_error_info = None
    event.processed = True

    if next_status == "paid":
        payment.paid_at = payment.paid_at or utcnow()
        order.creation_status = order.creation_status if order.iiko_order_id else "PaymentConfirmed"
    elif next_status in {"payment_failed", "payment_cancelled", "payment_expired"}:
        payment.failed_at = payment.failed_at or utcnow()
        order.creation_status = "PaymentFailed"

    await db.commit()

    if next_status == "paid":
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
    terminal_group_id = local_order.terminal_group_id or await get_order_terminal_group_id(access_token, organization)
    order_body = dict(local_order.iiko_order_payload)

    try:
        data = await request_iiko_json(
            "/api/1/deliveries/create",
            access_token,
            json_body={
                "organizationId": organization.iiko_organization_id,
                "terminalGroupId": terminal_group_id,
                "order": order_body,
            },
        )
    except IikoTerminalError as exc:
        local_order.creation_status = "IikoCreateFailed"
        local_order.error_info = {"message": str(exc)}
        await db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"iiko order creation failed: {exc}") from exc

    order_info = data.get("orderInfo")
    if not isinstance(order_info, dict):
        local_order.creation_status = "IikoCreateFailed"
        local_order.error_info = {"message": "iiko did not return orderInfo"}
        local_order.iiko_create_response = data
        await db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "iiko did not return orderInfo")

    update_local_order_from_create_response(local_order, data, order_info)
    await db.commit()
    return True


async def dispatch_paid_orders_once() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.scalars(
            select(Order.id)
            .where(
                Order.payment_status == "paid",
                Order.iiko_order_id.is_(None),
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

    payment.last_notification = state
    payment.status = next_status
    order = payment.order
    order.payment_status = next_status
    order.payment_error_info = None

    if next_status == "paid":
        payment.paid_at = payment.paid_at or utcnow()
        order.creation_status = order.creation_status if order.iiko_order_id else "PaymentConfirmed"
    elif next_status in {"payment_failed", "payment_cancelled", "payment_expired"}:
        payment.failed_at = payment.failed_at or utcnow()
        order.creation_status = "PaymentFailed"

    await db.commit()

    if next_status == "paid":
        await dispatch_paid_order_to_iiko(db, order.id)


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
) -> Order:
    order = Order(
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
        delivery_point=payload.delivery_point.model_dump(by_alias=True) if payload.delivery_point else None,
        items=[item.model_dump(by_alias=True) for item in payload.items],
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
        "externalNumber": str(order.id),
    }
    if organization.iiko_online_payment_type_id:
        iiko_order_payload["payments"] = [build_iiko_online_payment(organization, amount_kopecks)]
    order.iiko_order_payload = iiko_order_payload
    await db.commit()
    await db.refresh(order)
    return order


async def resolve_local_status_order(db: AsyncSession, order_id: str, *, customer: Customer | None = None) -> Order | None:
    try:
        parsed_order_id = UUID(order_id)
    except ValueError:
        return None

    statement = (
        select(Order)
        .options(selectinload(Order.organization))
        .where(Order.id == parsed_order_id)
    )
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


def calculate_order_amount_kopecks(order_body: dict[str, Any]) -> int:
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
    if item.modifiers:
        result["modifiers"] = [
            {
                key: value
                for key, value in {
                    "productId": modifier.product_id,
                    "productGroupId": modifier.product_group_id,
                    "amount": modifier.amount,
                    "price": modifier.price,
                }.items()
                if value is not None
            }
            for modifier in item.modifiers
        ]

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
            }

    return None


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
        if str(price.get("organizationId")) == iiko_organization_id:
            return parse_float(price.get("price"))

    if len(prices) == 1:
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


def parse_uuid(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None
