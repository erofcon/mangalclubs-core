from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.datastructures import UploadFile

from app.models.booking import Booking, BookingCategory, BookingImage
from app.models.organization import Organization
from app.schemas.booking import BookingCategoryCreate, BookingCategoryUpdate, BookingCreate, BookingUpdate
from app.services.media import delete_local_media_file, save_media_upload


def category_query(*, include_inactive: bool = False):
    statement = select(BookingCategory)
    if not include_inactive:
        statement = statement.where(BookingCategory.is_active.is_(True))
    return statement


def category_with_bookings_query(*, include_inactive: bool = False):
    bookings_loader = selectinload(BookingCategory.bookings)
    if not include_inactive:
        bookings_loader = selectinload(BookingCategory.bookings.and_(Booking.is_active.is_(True)))

    statement = select(BookingCategory).options(bookings_loader.selectinload(Booking.media))
    if not include_inactive:
        statement = statement.where(BookingCategory.is_active.is_(True))
    return statement


def booking_query(*, include_inactive: bool = False):
    statement = select(Booking).options(
        selectinload(Booking.organization),
        selectinload(Booking.category),
        selectinload(Booking.media),
    )
    if not include_inactive:
        statement = statement.where(Booking.is_active.is_(True)).where(
            Booking.category.has(BookingCategory.is_active.is_(True))
        )
    return statement


async def ensure_organization_exists(db: AsyncSession, organization_id: UUID) -> None:
    if not await db.scalar(select(Organization.id).where(Organization.id == organization_id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")


async def get_category_by_id(
    db: AsyncSession,
    category_id: UUID,
    *,
    include_inactive: bool = False,
) -> BookingCategory:
    category = await db.scalar(category_query(include_inactive=include_inactive).where(BookingCategory.id == category_id))
    if not category:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Booking category not found")

    return category


async def get_booking_by_id(
    db: AsyncSession,
    booking_id: UUID,
    *,
    include_inactive: bool = False,
) -> Booking:
    booking = await db.scalar(booking_query(include_inactive=include_inactive).where(Booking.id == booking_id))
    if not booking:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Booking not found")

    return booking


async def list_booking_categories(
    db: AsyncSession,
    organization_id: UUID | None = None,
    organization_slug: str | None = None,
) -> list[BookingCategory]:
    # Categories are global, so organization query parameters are intentionally
    # ignored for backward-compatible endpoint signatures.
    del organization_id, organization_slug
    statement = category_query()

    result = await db.scalars(statement.order_by(BookingCategory.sort_order, BookingCategory.title))
    return list(result.unique())


async def create_booking_category(db: AsyncSession, payload: BookingCategoryCreate) -> BookingCategory:
    category = BookingCategory(
        title=payload.title,
        description=payload.description,
        preview_url=str(payload.preview_url) if payload.preview_url is not None else None,
        sort_order=payload.sort_order,
        is_active=payload.is_active,
    )
    db.add(category)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Booking category already exists")

    return await get_category_by_id(db, category.id, include_inactive=True)


async def update_booking_category(
    db: AsyncSession,
    category_id: UUID,
    payload: BookingCategoryUpdate,
) -> BookingCategory:
    category = await db.scalar(
        category_with_bookings_query(include_inactive=True).where(BookingCategory.id == category_id)
    )
    if not category:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Booking category not found")

    data = payload.model_dump(exclude_unset=True)

    old_preview_url: str | None = None

    for field in ("title", "description", "sort_order", "is_active"):
        if field in data:
            setattr(category, field, data[field])

    if "preview_url" in data:
        next_preview_url = str(payload.preview_url) if payload.preview_url is not None else None
        if category.preview_url != next_preview_url:
            old_preview_url = category.preview_url
        category.preview_url = next_preview_url

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Booking category already exists")

    delete_local_media_file(old_preview_url)
    return await get_category_by_id(db, category.id, include_inactive=True)


async def delete_booking_category(db: AsyncSession, category_id: UUID) -> None:
    category = await db.scalar(
        category_with_bookings_query(include_inactive=True).where(BookingCategory.id == category_id)
    )
    if not category:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Booking category not found")

    media_urls = [category.preview_url]
    for booking in category.bookings:
        media_urls.append(booking.preview_url)
        media_urls.extend(image.url for image in booking.media)

    await db.delete(category)
    await db.commit()

    for media_url in media_urls:
        delete_local_media_file(media_url)


async def upload_booking_category_preview(
    db: AsyncSession,
    category_id: UUID,
    file: UploadFile,
) -> BookingCategory:
    category = await get_category_by_id(db, category_id, include_inactive=True)

    old_preview_url = category.preview_url
    category.preview_url = await save_media_upload(file, "booking-categories", str(category.id))
    await db.commit()

    delete_local_media_file(old_preview_url)
    return await get_category_by_id(db, category.id, include_inactive=True)


async def list_bookings(
    db: AsyncSession,
    organization_id: UUID | None = None,
    organization_slug: str | None = None,
    category_id: UUID | None = None,
) -> list[Booking]:
    statement = booking_query()

    if organization_id is not None:
        statement = statement.where(Booking.organization_id == organization_id)

    if organization_slug is not None:
        statement = statement.join(Booking.organization).where(Organization.slug == organization_slug)

    if category_id is not None:
        statement = statement.where(Booking.category_id == category_id)

    result = await db.scalars(statement.order_by(Booking.sort_order, Booking.title))
    return list(result.unique())


async def create_booking(db: AsyncSession, payload: BookingCreate) -> Booking:
    await validate_booking_links(db, payload.organization_id, payload.category_id)

    booking = Booking(
        organization_id=payload.organization_id,
        category_id=payload.category_id,
        title=payload.title,
        description=payload.description,
        long_description=payload.long_description,
        preview_url=str(payload.preview_url) if payload.preview_url is not None else None,
        sort_order=payload.sort_order,
        is_active=payload.is_active,
    )
    replace_booking_images(booking, collect_booking_images(payload))
    db.add(booking)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Booking already exists")

    return await get_booking_by_id(db, booking.id, include_inactive=True)


async def update_booking(db: AsyncSession, booking_id: UUID, payload: BookingUpdate) -> Booking:
    booking = await get_booking_by_id(db, booking_id, include_inactive=True)
    data = payload.model_dump(exclude_unset=True)

    next_organization_id = payload.organization_id or booking.organization_id
    next_category_id = payload.category_id or booking.category_id
    if payload.organization_id is not None or payload.category_id is not None:
        await validate_booking_links(db, next_organization_id, next_category_id)

    old_media_urls: list[str | None] = []

    for field in ("organization_id", "category_id", "title", "description", "long_description", "sort_order", "is_active"):
        if field in data:
            setattr(booking, field, data[field])

    if "preview_url" in data:
        next_preview_url = str(payload.preview_url) if payload.preview_url is not None else None
        if booking.preview_url != next_preview_url:
            old_media_urls.append(booking.preview_url)
        booking.preview_url = next_preview_url

    if payload.images is not None:
        current_images = list(booking.media)
        next_images = list(payload.images)

        ensure_booking_images_limit(next_images)
        new_image_urls = {str(image.url) for image in next_images}
        old_media_urls.extend(image.url for image in current_images if image.url not in new_image_urls)
        replace_booking_images(booking, next_images)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Booking already exists")

    for media_url in old_media_urls:
        delete_local_media_file(media_url)

    return await get_booking_by_id(db, booking.id, include_inactive=True)


async def delete_booking(db: AsyncSession, booking_id: UUID) -> None:
    booking = await get_booking_by_id(db, booking_id, include_inactive=True)
    media_urls = [booking.preview_url, *(image.url for image in booking.media)]

    await db.delete(booking)
    await db.commit()

    for media_url in media_urls:
        delete_local_media_file(media_url)


async def upload_booking_preview(db: AsyncSession, booking_id: UUID, file: UploadFile) -> Booking:
    booking = await get_booking_by_id(db, booking_id, include_inactive=True)

    old_preview_url = booking.preview_url
    booking.preview_url = await save_media_upload(file, "bookings", str(booking.id))
    await db.commit()

    delete_local_media_file(old_preview_url)
    return await get_booking_by_id(db, booking.id, include_inactive=True)


async def add_booking_images(
    db: AsyncSession,
    booking_id: UUID,
    files: list[UploadFile],
    sort_order: int = 0,
) -> Booking:
    booking = await get_booking_by_id(db, booking_id, include_inactive=True)
    ensure_booking_images_limit([*booking.media, *files])

    for index, file in enumerate(files):
        image = BookingImage(
            booking_id=booking.id,
            url=await save_media_upload(file, "bookings", str(booking.id)),
            sort_order=sort_order + index,
        )
        db.add(image)

    await db.commit()
    return await get_booking_by_id(db, booking.id, include_inactive=True)


async def delete_booking_image(db: AsyncSession, booking_id: UUID, image_id: UUID) -> Booking:
    booking = await get_booking_by_id(db, booking_id, include_inactive=True)
    image = next((item for item in booking.media if item.id == image_id), None)
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Booking image not found")

    image_url = image.url
    await db.delete(image)
    await db.commit()

    delete_local_media_file(image_url)
    return await get_booking_by_id(db, booking.id, include_inactive=True)


async def validate_booking_links(db: AsyncSession, organization_id: UUID, category_id: UUID) -> None:
    await ensure_organization_exists(db, organization_id)
    if not await db.scalar(select(BookingCategory.id).where(BookingCategory.id == category_id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Booking category not found")


def replace_booking_images(booking: Booking, images) -> None:
    booking.media = [
        BookingImage(
            url=str(item.url),
            alt_text=item.alt_text,
            sort_order=item.sort_order,
        )
        for item in images
    ]


def collect_booking_images(payload: BookingCreate) -> list:
    images = list(payload.images)
    ensure_booking_images_limit(images)
    return images


def ensure_booking_images_limit(images) -> None:
    if len(images) > 24:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A booking can have at most 24 images")
