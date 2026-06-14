from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.delivery import DeliveryZone
from app.schemas.delivery import DeliveryZoneCreate, DeliveryZoneUpdate


async def list_delivery_zones(db: AsyncSession) -> list[DeliveryZone]:
    result = await db.scalars(select(DeliveryZone).order_by(DeliveryZone.distance_from_km, DeliveryZone.distance_to_km))
    return list(result)


async def get_delivery_zone_by_id(
    db: AsyncSession,
    zone_id: UUID,
) -> DeliveryZone:
    zone = await db.get(DeliveryZone, zone_id)
    if not zone:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Delivery zone not found")

    return zone


async def create_delivery_zone(db: AsyncSession, payload: DeliveryZoneCreate) -> DeliveryZone:
    await ensure_delivery_zone_does_not_overlap(
        db,
        payload.distance_from_km,
        payload.distance_to_km,
    )

    zone = DeliveryZone(
        distance_from_km=payload.distance_from_km,
        distance_to_km=payload.distance_to_km,
        price=payload.price,
    )
    db.add(zone)
    await db.commit()
    await db.refresh(zone)
    return zone


async def update_delivery_zone(
    db: AsyncSession,
    zone_id: UUID,
    payload: DeliveryZoneUpdate,
) -> DeliveryZone:
    zone = await get_delivery_zone_by_id(db, zone_id)
    data = payload.model_dump(exclude_unset=True)

    next_distance_from = payload.distance_from_km if payload.distance_from_km is not None else zone.distance_from_km
    next_distance_to = payload.distance_to_km if payload.distance_to_km is not None else zone.distance_to_km

    if next_distance_to <= next_distance_from:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "distance_to_km must be greater than distance_from_km")

    await ensure_delivery_zone_does_not_overlap(
        db,
        next_distance_from,
        next_distance_to,
        exclude_zone_id=zone.id,
    )

    for field in ("distance_from_km", "distance_to_km", "price"):
        if field in data:
            setattr(zone, field, data[field])

    await db.commit()
    await db.refresh(zone)
    return zone


async def delete_delivery_zone(db: AsyncSession, zone_id: UUID) -> None:
    zone = await get_delivery_zone_by_id(db, zone_id)
    await db.delete(zone)
    await db.commit()


async def ensure_delivery_zone_does_not_overlap(
    db: AsyncSession,
    distance_from_km: Decimal,
    distance_to_km: Decimal,
    *,
    exclude_zone_id: UUID | None = None,
) -> None:
    statement = select(DeliveryZone.id).where(
        DeliveryZone.distance_from_km < distance_to_km,
        DeliveryZone.distance_to_km > distance_from_km,
    )

    if exclude_zone_id is not None:
        statement = statement.where(DeliveryZone.id != exclude_zone_id)

    if await db.scalar(statement):
        raise HTTPException(status.HTTP_409_CONFLICT, "Delivery zone overlaps an active zone")
