from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.datastructures import UploadFile

from app.core.config import settings
from app.models.organization import Organization, OrganizationWorkingHour
from app.schemas.organization import OrganizationCreate, OrganizationUpdate


ALLOWED_PHOTO_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
MAX_PHOTO_SIZE_BYTES = 8 * 1024 * 1024


def organization_query():
    return select(Organization).options(selectinload(Organization.working_hours))


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
        intro=payload.intro,
        latitude=payload.coordinates.latitude,
        longitude=payload.coordinates.longitude,
        photo_url=str(payload.photo_url) if payload.photo_url is not None else None,
    )
    replace_working_hours(organization, payload.working_hours)

    db.add(organization)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Organization already exists")

    return await get_organization_by_id(db, organization.id)


async def update_organization(
    db: AsyncSession,
    organization_id: UUID,
    payload: OrganizationUpdate,
) -> Organization:
    organization = await get_organization_by_id(db, organization_id)
    data = payload.model_dump(exclude_unset=True)

    for field in ("slug", "name", "city", "address", "phone", "intro"):
        if field in data:
            setattr(organization, field, data[field])

    if "coordinates" in data and payload.coordinates is not None:
        organization.latitude = payload.coordinates.latitude
        organization.longitude = payload.coordinates.longitude

    if "photo_url" in data:
        organization.photo_url = str(payload.photo_url) if payload.photo_url is not None else None

    if payload.working_hours is not None:
        replace_working_hours(organization, payload.working_hours)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Organization already exists")

    return await get_organization_by_id(db, organization.id)


async def delete_organization(db: AsyncSession, organization_id: UUID) -> None:
    organization = await get_organization_by_id(db, organization_id)
    delete_local_media_file(organization.photo_url)
    await db.delete(organization)
    await db.commit()


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
    organization.working_hours = [
        OrganizationWorkingHour(
            weekday=item.weekday,
            is_closed=item.is_closed,
            opens_at=item.opens_at,
            closes_at=item.closes_at,
        )
        for item in working_hours
    ]
