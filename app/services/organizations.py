from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.datastructures import UploadFile

from app.core.config import settings
from app.models.order import Order
from app.models.organization import Organization, OrganizationWorkingHour
from app.schemas.organization import OrganizationCreate, OrganizationUpdate
from app.services.iiko import IikoAuthorizationError, IikoTerminalError, authorize_organization, get_valid_token, request_iiko_json


ALLOWED_PHOTO_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
MAX_PHOTO_SIZE_BYTES = 8 * 1024 * 1024


def organization_query():
    return select(Organization).options(
        selectinload(Organization.working_hours),
        selectinload(Organization.iiko_token),
        selectinload(Organization.iiko_menu_snapshot),
    )


async def list_organizations(db: AsyncSession) -> list[Organization]:
    result = await db.scalars(organization_query().order_by(Organization.name))
    return list(result.unique())


async def get_organization_by_slug(db: AsyncSession, slug: str) -> Organization:
    organization = await db.scalar(organization_query().where(Organization.slug == slug))
    if not organization:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")

    return organization


async def get_organization_by_id(db: AsyncSession, organization_id: UUID) -> Organization:
    organization = await db.scalar(organization_query().where(Organization.id == organization_id))
    if not organization:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")

    return organization


async def create_organization(db: AsyncSession, payload: OrganizationCreate) -> Organization:
    if await db.scalar(select(Organization.id).where(Organization.slug == payload.slug)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Organization already exists")

    organization = Organization(
        slug=payload.slug,
        name=payload.name,
        city=payload.city,
        address=payload.address,
        phone=payload.phone,
        whatsapp_phone=payload.whatsapp_phone,
        intro=payload.intro,
        latitude=payload.coordinates.latitude,
        longitude=payload.coordinates.longitude,
        photo_url=str(payload.photo_url) if payload.photo_url is not None else None,
        iiko_api_login=payload.iiko_api_login,
        iiko_organization_id=payload.iiko_organization_id,
        iiko_online_payment_type_id=payload.iiko_online_payment_type_id,
        iiko_online_payment_type_kind=payload.iiko_online_payment_type_kind,
        tbank_terminal_key=payload.tbank_terminal_key,
        tbank_password=payload.tbank_password,
        accepts_pickup=payload.accepts_pickup,
        accepts_delivery=payload.accepts_delivery,
        is_default_delivery=payload.is_default_delivery,
    )
    replace_working_hours(organization, payload.working_hours)
    validate_organization_delivery_settings(organization)

    db.add(organization)
    if organization.is_default_delivery:
        await reset_default_delivery(db, organization.id)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Organization already exists")

    if organization.iiko_api_login:
        await authorize_organization(db, organization)

    return await get_organization_by_id(db, organization.id)


async def update_organization(
    db: AsyncSession,
    organization_id: UUID,
    payload: OrganizationUpdate,
) -> Organization:
    organization = await get_organization_by_id(db, organization_id)
    previous_iiko_organization_id = organization.iiko_organization_id
    data = payload.model_dump(exclude_unset=True)

    for field in (
        "slug",
        "name",
        "city",
        "address",
        "phone",
        "whatsapp_phone",
        "intro",
        "iiko_api_login",
        "iiko_organization_id",
        "iiko_online_payment_type_id",
        "iiko_online_payment_type_kind",
        "tbank_terminal_key",
        "tbank_password",
        "accepts_pickup",
        "accepts_delivery",
        "is_default_delivery",
    ):
        if field in data:
            if field == "iiko_online_payment_type_kind" and data[field] is None:
                continue
            setattr(organization, field, data[field])

    if "coordinates" in data and payload.coordinates is not None:
        organization.latitude = payload.coordinates.latitude
        organization.longitude = payload.coordinates.longitude

    if "photo_url" in data:
        organization.photo_url = str(payload.photo_url) if payload.photo_url is not None else None

    if payload.working_hours is not None:
        replace_working_hours(organization, payload.working_hours)

    if (
        "iiko_organization_id" in data
        and organization.iiko_organization_id != previous_iiko_organization_id
        and organization.iiko_menu_snapshot is not None
    ):
        organization.iiko_menu_snapshot.last_error = (
            "iiko organization id changed; waiting for menu sync with the new organization"
        )

    validate_organization_delivery_settings(organization)

    if organization.is_default_delivery:
        await reset_default_delivery(db, organization.id)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Organization already exists")

    if "iiko_api_login" in data or "iiko_organization_id" in data:
        if organization.iiko_api_login:
            await authorize_organization(db, organization)
        elif organization.iiko_token:
            await db.delete(organization.iiko_token)
            await db.commit()

    return await get_organization_by_id(db, organization.id)


async def delete_organization(db: AsyncSession, organization_id: UUID) -> None:
    organization = await get_organization_by_id(db, organization_id)
    has_orders = await db.scalar(select(Order.id).where(Order.organization_id == organization.id).limit(1))
    if has_orders:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Organization cannot be deleted because it has orders",
        )

    photo_url = organization.photo_url
    await db.delete(organization)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Organization cannot be deleted because it is used by related records",
        ) from exc

    delete_local_media_file(photo_url)


async def upload_organization_photo(
    db: AsyncSession,
    organization_id: UUID,
    file: UploadFile,
) -> Organization:
    organization = await get_organization_by_id(db, organization_id)
    extension = validate_photo_upload(file)
    photo_dir = Path(settings.media_root) / "organizations"
    photo_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{organization.id}-{uuid4().hex}{extension}"
    destination = photo_dir / filename

    written = 0
    try:
        with destination.open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_PHOTO_SIZE_BYTES:
                    raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Photo is too large")
                target.write(chunk)
    except Exception:
        if destination.exists():
            destination.unlink()
        raise
    finally:
        await file.close()

    delete_local_media_file(organization.photo_url)
    organization.photo_url = f"{settings.media_url.rstrip('/')}/organizations/{filename}"
    await db.commit()

    return await get_organization_by_id(db, organization.id)


async def list_iiko_payment_types(db: AsyncSession, organization_id: UUID) -> dict:
    organization = await get_organization_by_id(db, organization_id)
    if not organization.iiko_api_login or not organization.iiko_organization_id:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Organization iiko is not configured")

    try:
        access_token = await get_valid_token(db, organization.id)
        data = await request_iiko_json(
            "/api/1/payment_types",
            access_token,
            json_body={"organizationIds": [organization.iiko_organization_id]},
        )
    except IikoAuthorizationError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "iiko authorization is not available") from exc
    except IikoTerminalError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"iiko payment types request failed: {exc}") from exc

    return data


def validate_photo_upload(file: UploadFile) -> str:
    extension = ALLOWED_PHOTO_CONTENT_TYPES.get(file.content_type or "")
    if not extension:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only JPEG, PNG, and WebP photos are supported")

    return extension


def delete_local_media_file(photo_url: str | None) -> None:
    media_url = settings.media_url.rstrip("/")
    if not photo_url or not photo_url.startswith(f"{media_url}/"):
        return

    media_root = Path(settings.media_root).resolve()
    relative_url = photo_url.removeprefix(f"{media_url}/")
    target = (media_root / relative_url).resolve()

    if media_root not in target.parents or not target.is_file():
        return

    target.unlink()


def replace_working_hours(organization: Organization, working_hours) -> None:
    existing_by_weekday = {item.weekday: item for item in organization.working_hours}
    next_hours = []

    for item in working_hours:
        working_hour = existing_by_weekday.get(item.weekday)
        if working_hour is None:
            working_hour = OrganizationWorkingHour(weekday=item.weekday)

        working_hour.is_closed = item.is_closed
        working_hour.opens_at = item.opens_at
        working_hour.closes_at = item.closes_at
        next_hours.append(working_hour)

    organization.working_hours = next_hours


async def reset_default_delivery(db: AsyncSession, organization_id: UUID) -> None:
    result = await db.scalars(
        select(Organization).where(
            Organization.id != organization_id,
            Organization.is_default_delivery.is_(True),
        )
    )
    for organization in result:
        organization.is_default_delivery = False


def validate_organization_delivery_settings(organization: Organization) -> None:
    if organization.is_default_delivery and not organization.accepts_delivery:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Default delivery organization must accept delivery orders",
        )
