import json
from decimal import Decimal
from math import atan2, cos, isfinite, radians, sin, sqrt
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.delivery import DeliveryZone
from app.models.organization import Organization
from app.schemas.delivery import DeliveryCheckIn
from app.schemas.delivery import DeliveryZoneCreate, DeliveryZoneUpdate
from app.services.geocoding import resolve_address_for_coordinates

MAX_DELIVERY_ZONE_DISTANCE_KM = Decimal("9999.99")

DEFAULT_GROZNY_DELIVERY_AREA_GEOJSON: dict = {
    "type": "Polygon",
    "coordinates": [
        [
            [45.4324039, 43.3832836],
            [45.4444867, 43.3729436],
            [45.4902789, 43.3682455],
            [45.504525, 43.354887],
            [45.5063921, 43.3577997],
            [45.5176985, 43.3594648],
            [45.5226271, 43.3582326],
            [45.5258643, 43.352055],
            [45.5373703, 43.3530678],
            [45.549026, 43.347122],
            [45.5638257, 43.3465481],
            [45.57914, 43.3181569],
            [45.606125, 43.3155082],
            [45.6000405, 43.3013323],
            [45.5926324, 43.3021566],
            [45.5873407, 43.2932621],
            [45.6028298, 43.2721414],
            [45.5918589, 43.268372],
            [45.5897853, 43.2588696],
            [45.5756567, 43.2517621],
            [45.5896911, 43.2419966],
            [45.5887866, 43.23818],
            [45.5984538, 43.2365409],
            [45.6065997, 43.2389285],
            [45.6084791, 43.2331866],
            [45.6047351, 43.2292576],
            [45.6077005, 43.2153624],
            [45.7019216, 43.1993581],
            [45.7430436, 43.1783006],
            [45.7489382, 43.203605],
            [45.7446407, 43.2222399],
            [45.7487646, 43.2351385],
            [45.7566656, 43.2318705],
            [45.7658546, 43.2351797],
            [45.7731125, 43.2456988],
            [45.7718697, 43.250024],
            [45.7749225, 43.2512682],
            [45.7734683, 43.2584678],
            [45.7633945, 43.2646638],
            [45.7705924, 43.2829626],
            [45.8083899, 43.2914781],
            [45.8154297, 43.3022617],
            [45.8092534, 43.3098504],
            [45.79954, 43.3094372],
            [45.8013574, 43.3227734],
            [45.798936, 43.3420034],
            [45.761812, 43.3419444],
            [45.7641737, 43.3433276],
            [45.7584733, 43.3471887],
            [45.7650962, 43.3476748],
            [45.7608783, 43.3514703],
            [45.7628242, 43.3533825],
            [45.7553091, 43.3529491],
            [45.7669921, 43.3626995],
            [45.7450264, 43.3611929],
            [45.7451054, 43.3954349],
            [45.7412136, 43.3967409],
            [45.7393492, 43.4161864],
            [45.7319589, 43.4270068],
            [45.6867791, 43.4356141],
            [45.6146947, 43.4382262],
            [45.5925186, 43.4300106],
            [45.5764479, 43.4303003],
            [45.5769186, 43.4218072],
            [45.5531942, 43.4192895],
            [45.535969, 43.420543],
            [45.5005332, 43.4307881],
            [45.468548, 43.432842],
            [45.4638535, 43.4260011],
            [45.455906, 43.4277854],
            [45.4605613, 43.4203259],
            [45.4586649, 43.3987955],
            [45.4729728, 43.3970521],
            [45.4705317, 43.3905226],
            [45.4420267, 43.3920428],
            [45.4373608, 43.3905243],
            [45.4324039, 43.3832836],
        ]
    ],
}


async def list_delivery_zones(db: AsyncSession) -> list[DeliveryZone]:
    result = await db.scalars(
        select(DeliveryZone).order_by(
            DeliveryZone.distance_from_km,
            DeliveryZone.distance_to_km.nulls_last(),
        )
    )
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
        delivery_time=payload.delivery_time,
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
    next_distance_to = data["distance_to_km"] if "distance_to_km" in data else zone.distance_to_km

    if next_distance_to is not None and next_distance_to <= next_distance_from:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "distance_to_km must be greater than distance_from_km")

    await ensure_delivery_zone_does_not_overlap(
        db,
        next_distance_from,
        next_distance_to,
        exclude_zone_id=zone.id,
    )

    for field in ("distance_from_km", "distance_to_km", "price", "delivery_time"):
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
    distance_to_km: Decimal | None,
    *,
    exclude_zone_id: UUID | None = None,
) -> None:
    statement = select(DeliveryZone.id).where(
        or_(DeliveryZone.distance_to_km.is_(None), DeliveryZone.distance_to_km > distance_from_km),
    )
    if distance_to_km is not None:
        statement = statement.where(DeliveryZone.distance_from_km < distance_to_km)

    if exclude_zone_id is not None:
        statement = statement.where(DeliveryZone.id != exclude_zone_id)

    if await db.scalar(statement):
        raise HTTPException(status.HTTP_409_CONFLICT, "Delivery zone overlaps an active zone")


async def get_delivery_settings(db: AsyncSession) -> dict:
    return {
        "delivery_area": get_delivery_area_geojson(),
        "pricing_zones": await list_delivery_zones(db),
        "yandex_maps_api_key": settings.yandex_maps_api_key,
    }


async def check_delivery(db: AsyncSession, payload: DeliveryCheckIn) -> dict:
    organization = await resolve_delivery_organization(
        db,
        organization_id=payload.organization_id,
        organization_slug=payload.organization_slug,
    )
    calculation = await calculate_delivery_for_coordinates(
        db,
        organization=organization,
        latitude=payload.coordinates.latitude,
        longitude=payload.coordinates.longitude,
    )
    calculation["address"] = await resolve_address_for_coordinates(
        latitude=payload.coordinates.latitude,
        longitude=payload.coordinates.longitude,
    )
    return calculation


async def calculate_delivery_for_coordinates(
    db: AsyncSession,
    *,
    organization: Organization,
    latitude: float,
    longitude: float,
) -> dict:
    validate_delivery_coordinates(latitude=latitude, longitude=longitude)

    distance_km = calculate_haversine_distance_km(
        float(organization.latitude),
        float(organization.longitude),
        latitude,
        longitude,
    )

    if not is_point_in_delivery_area(latitude=latitude, longitude=longitude):
        return unavailable_delivery_calculation("outside_delivery_area", distance_km)

    # DeliveryZone.distance_* are NUMERIC(6, 2), so PostgreSQL cannot bind a
    # larger value to the comparison. This can happen when coordinates come
    # from a bad IP geolocation result. Treat it as an unavailable delivery
    # instead of allowing a database exception to escape from the request.
    if distance_km > MAX_DELIVERY_ZONE_DISTANCE_KM:
        return unavailable_delivery_calculation("delivery_distance_out_of_range", distance_km)

    zone = await find_delivery_zone_for_distance(db, distance_km)
    if zone is None:
        return unavailable_delivery_calculation("delivery_tariff_not_configured", distance_km)

    return {
        "available": True,
        "reason": None,
        "distance_km": float(distance_km),
        "price": zone.price,
        "zone": zone,
        "address": None,
    }


async def ensure_delivery_available_for_coordinates(
    db: AsyncSession,
    *,
    organization: Organization,
    latitude: float,
    longitude: float,
) -> dict:
    calculation = await calculate_delivery_for_coordinates(
        db,
        organization=organization,
        latitude=latitude,
        longitude=longitude,
    )
    if not calculation["available"]:
        reason = calculation["reason"]
        if reason == "outside_delivery_area":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Delivery address is outside Grozny delivery area")
        if reason == "delivery_distance_out_of_range":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Delivery address coordinates are invalid")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Delivery tariff is not configured")

    return calculation


async def resolve_delivery_organization(
    db: AsyncSession,
    *,
    organization_id: UUID | None = None,
    organization_slug: str | None = None,
) -> Organization:
    statement = select(Organization).where(Organization.accepts_delivery.is_(True))
    if organization_id is not None:
        statement = statement.where(Organization.id == organization_id)
    elif organization_slug is not None:
        statement = statement.where(Organization.slug == organization_slug.strip().lower())
    else:
        statement = statement.where(Organization.is_default_delivery.is_(True)).limit(1)

    organization = await db.scalar(statement)
    if not organization:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Delivery organization not found")

    return organization


async def find_delivery_zone_for_distance(db: AsyncSession, distance_km: Decimal) -> DeliveryZone | None:
    if distance_km > MAX_DELIVERY_ZONE_DISTANCE_KM:
        return None

    return await db.scalar(
        select(DeliveryZone)
        .where(
            DeliveryZone.distance_from_km <= distance_km,
            or_(DeliveryZone.distance_to_km.is_(None), DeliveryZone.distance_to_km > distance_km),
        )
        .order_by(DeliveryZone.distance_from_km.desc())
        .limit(1)
    )


def calculate_haversine_distance_km(
    origin_latitude: float,
    origin_longitude: float,
    target_latitude: float,
    target_longitude: float,
) -> Decimal:
    origin_latitude_rad = radians(origin_latitude)
    target_latitude_rad = radians(target_latitude)
    delta_latitude = radians(target_latitude - origin_latitude)
    delta_longitude = radians(target_longitude - origin_longitude)

    haversine = (
        sin(delta_latitude / 2) ** 2
        + cos(origin_latitude_rad) * cos(target_latitude_rad) * sin(delta_longitude / 2) ** 2
    )
    # Floating-point rounding can produce a value just outside [0, 1].
    haversine = min(1.0, max(0.0, haversine))
    distance = 2 * 6371.0088 * atan2(sqrt(haversine), sqrt(1 - haversine))
    return Decimal(str(distance)).quantize(Decimal("0.01"))


def validate_delivery_coordinates(*, latitude: float, longitude: float) -> None:
    if (
        not isfinite(latitude)
        or not isfinite(longitude)
        or not (-90 <= latitude <= 90)
        or not (-180 <= longitude <= 180)
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid delivery coordinates")


def unavailable_delivery_calculation(reason: str, distance_km: Decimal) -> dict:
    return {
        "available": False,
        "reason": reason,
        "distance_km": float(distance_km),
        "price": None,
        "zone": None,
        "address": None,
    }


def get_delivery_area_geojson() -> dict:
    if not settings.delivery_area_geojson:
        return DEFAULT_GROZNY_DELIVERY_AREA_GEOJSON

    try:
        area = json.loads(settings.delivery_area_geojson)
    except json.JSONDecodeError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Delivery area GeoJSON is invalid") from exc

    if not isinstance(area, dict) or area.get("type") not in {"Polygon", "MultiPolygon"}:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Delivery area GeoJSON must be Polygon or MultiPolygon")

    return area


def is_point_in_delivery_area(*, latitude: float, longitude: float) -> bool:
    area = get_delivery_area_geojson()
    coordinates = area.get("coordinates")
    if area.get("type") == "Polygon":
        return is_point_in_polygon(longitude, latitude, coordinates)
    if area.get("type") == "MultiPolygon":
        return any(is_point_in_polygon(longitude, latitude, polygon) for polygon in coordinates or [])
    return False


def is_point_in_polygon(x: float, y: float, polygon: list) -> bool:
    if not polygon:
        return False

    outer_ring = polygon[0]
    if not is_point_in_ring(x, y, outer_ring):
        return False

    holes = polygon[1:]
    return not any(is_point_in_ring(x, y, ring) for ring in holes)


def is_point_in_ring(x: float, y: float, ring: list) -> bool:
    inside = False
    if len(ring) < 3:
        return False

    previous_x, previous_y = ring[-1]
    for current_x, current_y in ring:
        if is_point_on_segment(x, y, previous_x, previous_y, current_x, current_y):
            return True
        intersects = (current_y > y) != (previous_y > y)
        if intersects:
            intersection_x = (previous_x - current_x) * (y - current_y) / (previous_y - current_y) + current_x
            if x < intersection_x:
                inside = not inside
        previous_x, previous_y = current_x, current_y

    return inside


def is_point_on_segment(
    x: float,
    y: float,
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
) -> bool:
    cross_product = (y - start_y) * (end_x - start_x) - (x - start_x) * (end_y - start_y)
    if abs(cross_product) > 1e-10:
        return False

    return min(start_x, end_x) <= x <= max(start_x, end_x) and min(start_y, end_y) <= y <= max(start_y, end_y)
