from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin, get_current_customer, get_optional_current_customer
from app.db.session import get_db
from app.models.customer import Customer
from app.models.staff import StaffUser
from app.schemas.order import (
    CustomerOrderOut,
    OrderCreateIn,
    OrderCreateOut,
    OrderStatusOut,
    OrderStoredOut,
    PaymentEventOut,
)
from app.services.orders import (
    create_order_payment,
    dispatch_paid_order_to_iiko,
    get_iiko_order_status,
    get_stored_order,
    handle_tbank_webhook,
    list_order_payment_events,
    list_customer_current_orders,
    list_customer_order_history,
    list_stored_orders,
)

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", response_model=OrderCreateOut, status_code=status.HTTP_201_CREATED)
async def orders_create(
    payload: OrderCreateIn,
    db: AsyncSession = Depends(get_db),
    customer: Customer | None = Depends(get_optional_current_customer),
):
    return await create_order_payment(db, payload, customer=customer)


@router.post("/payments/tbank/webhook", include_in_schema=False)
async def orders_tbank_webhook(
    payload: dict,
    db: AsyncSession = Depends(get_db),
):
    await handle_tbank_webhook(db, payload)
    return Response(content="OK", media_type="text/plain")


@router.get("/me/current", response_model=list[CustomerOrderOut])
async def orders_my_current(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    customer: Customer = Depends(get_current_customer),
):
    return await list_customer_current_orders(db, customer, limit=limit, offset=offset)


@router.get("/me/history", response_model=list[CustomerOrderOut])
async def orders_my_history(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    customer: Customer = Depends(get_current_customer),
):
    return await list_customer_order_history(db, customer, limit=limit, offset=offset)


@router.get("/me/{local_order_id}/status", response_model=OrderStatusOut)
async def orders_my_status(
    local_order_id: str,
    db: AsyncSession = Depends(get_db),
    customer: Customer = Depends(get_current_customer),
):
    return await get_iiko_order_status(
        db,
        order_id=str(local_order_id),
        organization_id=None,
        organization_slug=None,
        customer=customer,
    )


@router.get("/admin/by-number/{public_number}", response_model=OrderStoredOut)
async def orders_admin_get_by_number(
    public_number: str,
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await get_stored_order(db, public_number)


@router.get("/admin", response_model=list[OrderStoredOut])
async def orders_admin_list(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await list_stored_orders(db, limit=limit, offset=offset)


@router.get("/admin/{local_order_id}", response_model=OrderStoredOut)
async def orders_admin_get(
    local_order_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await get_stored_order(db, local_order_id)


@router.get("/admin/by-number/{public_number}/payment-events", response_model=list[PaymentEventOut])
async def orders_admin_payment_events_by_number(
    public_number: str,
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    order = await get_stored_order(db, public_number)
    return await list_order_payment_events(db, order.id)


@router.get("/admin/{local_order_id}/payment-events", response_model=list[PaymentEventOut])
async def orders_admin_payment_events(
    local_order_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await list_order_payment_events(db, local_order_id)


@router.post("/admin/{local_order_id}/dispatch-iiko", status_code=status.HTTP_202_ACCEPTED)
async def orders_admin_dispatch_iiko(
    local_order_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    dispatched = await dispatch_paid_order_to_iiko(db, local_order_id)
    return {"dispatched": dispatched}


@router.get("/{order_id}/status", response_model=OrderStatusOut)
async def orders_status(
    order_id: str,
    organization_id: UUID | None = Query(default=None, alias="organizationId"),
    organization_slug: str | None = Query(default=None, alias="organizationSlug"),
    db: AsyncSession = Depends(get_db),
):
    return await get_iiko_order_status(
        db,
        order_id=order_id,
        organization_id=organization_id,
        organization_slug=organization_slug,
    )
