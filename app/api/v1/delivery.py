from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.db.session import get_db
from app.models.staff import StaffUser
from app.schemas.delivery import (
    DeliveryCalculationOut,
    DeliveryCheckIn,
    DeliverySettingsOut,
    DeliveryZoneCreate,
    DeliveryZoneOut,
    DeliveryZoneUpdate,
)
from app.services.delivery import (
    check_delivery,
    create_delivery_zone,
    delete_delivery_zone,
    get_delivery_zone_by_id,
    get_delivery_settings,
    list_delivery_zones,
    update_delivery_zone,
)

router = APIRouter(prefix="/delivery-zones", tags=["delivery-zones"])


@router.get("", response_model=list[DeliveryZoneOut])
async def delivery_zones_list(
    db: AsyncSession = Depends(get_db),
):
    return await list_delivery_zones(db)


@router.get("/settings", response_model=DeliverySettingsOut)
async def delivery_settings(
    db: AsyncSession = Depends(get_db),
):
    return await get_delivery_settings(db)


@router.post("/check", response_model=DeliveryCalculationOut)
async def delivery_check(
    payload: DeliveryCheckIn,
    db: AsyncSession = Depends(get_db),
):
    return await check_delivery(db, payload)


@router.get("/admin", response_model=list[DeliveryZoneOut])
async def delivery_zones_admin_list(
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await list_delivery_zones(db)


@router.get("/admin/{zone_id}", response_model=DeliveryZoneOut)
async def delivery_zones_admin_get(
    zone_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await get_delivery_zone_by_id(db, zone_id)


@router.get("/{zone_id}", response_model=DeliveryZoneOut)
async def delivery_zones_get(zone_id: UUID, db: AsyncSession = Depends(get_db)):
    return await get_delivery_zone_by_id(db, zone_id)


@router.post("", response_model=DeliveryZoneOut, status_code=status.HTTP_201_CREATED)
async def delivery_zones_create(
    payload: DeliveryZoneCreate,
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await create_delivery_zone(db, payload)


@router.patch("/{zone_id}", response_model=DeliveryZoneOut)
async def delivery_zones_update(
    zone_id: UUID,
    payload: DeliveryZoneUpdate,
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await update_delivery_zone(db, zone_id, payload)


@router.delete("/{zone_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delivery_zones_delete(
    zone_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    await delete_delivery_zone(db, zone_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
