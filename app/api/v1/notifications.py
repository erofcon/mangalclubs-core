from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_customer
from app.db.session import get_db
from app.models.customer import Customer
from app.schemas.notification import (
    CustomerDeviceOut,
    CustomerDeviceRegisterIn,
    CustomerUnreadNotificationsOut,
)
from app.services.notifications import (
    deactivate_customer_device,
    list_customer_unread_notifications,
    mark_customer_order_notifications_read,
    register_customer_device,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.post("/devices", response_model=CustomerDeviceOut)
async def notifications_register_device(
    payload: CustomerDeviceRegisterIn,
    db: AsyncSession = Depends(get_db),
    customer: Customer = Depends(get_current_customer),
):
    return await register_customer_device(db, customer, payload)


@router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def notifications_deactivate_device(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    customer: Customer = Depends(get_current_customer),
):
    await deactivate_customer_device(db, customer, device_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me/unread", response_model=CustomerUnreadNotificationsOut)
async def notifications_my_unread(
    db: AsyncSession = Depends(get_db),
    customer: Customer = Depends(get_current_customer),
):
    notifications = await list_customer_unread_notifications(db, customer)
    order_ids = list(dict.fromkeys(item.order_id for item in notifications))

    return {
        "count": len(notifications),
        "order_ids": order_ids,
        "notifications": notifications,
    }


@router.post("/me/orders/{order_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def notifications_mark_order_read(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    customer: Customer = Depends(get_current_customer),
):
    await mark_customer_order_notifications_read(db, customer, order_id=order_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
