from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.db.session import get_db
from app.models.booking import BookingImageOrientation
from app.models.staff import StaffUser
from app.schemas.booking import BookingCategoryCreate, BookingCategoryOut, BookingCategoryUpdate, BookingCreate, BookingOut, BookingUpdate
from app.services.bookings import (
    add_booking_images,
    create_booking,
    create_booking_category,
    delete_booking,
    delete_booking_category,
    delete_booking_image,
    get_booking_by_id,
    get_category_by_id,
    list_booking_categories,
    list_bookings,
    update_booking,
    update_booking_category,
    upload_booking_category_preview,
    upload_booking_preview,
)

router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.get("/categories", response_model=list[BookingCategoryOut])
async def booking_categories_list(
    organization_id: UUID | None = Query(default=None),
    organization_slug: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    return await list_booking_categories(db, organization_id=organization_id, organization_slug=organization_slug)


@router.get("/categories/{category_id}", response_model=BookingCategoryOut)
async def booking_categories_get(category_id: UUID, db: AsyncSession = Depends(get_db)):
    return await get_category_by_id(db, category_id)


@router.post("/categories", response_model=BookingCategoryOut, status_code=status.HTTP_201_CREATED)
async def booking_categories_create(
    payload: BookingCategoryCreate,
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await create_booking_category(db, payload)


@router.patch("/categories/{category_id}", response_model=BookingCategoryOut)
async def booking_categories_update(
    category_id: UUID,
    payload: BookingCategoryUpdate,
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await update_booking_category(db, category_id, payload)


@router.post("/categories/{category_id}/preview", response_model=BookingCategoryOut)
async def booking_categories_upload_preview(
    category_id: UUID,
    preview: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await upload_booking_category_preview(db, category_id, preview)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def booking_categories_delete(
    category_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    await delete_booking_category(db, category_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("", response_model=list[BookingOut])
async def bookings_list(
    organization_id: UUID | None = Query(default=None),
    organization_slug: str | None = Query(default=None),
    category_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    return await list_bookings(
        db,
        organization_id=organization_id,
        organization_slug=organization_slug,
        category_id=category_id,
    )


@router.get("/{booking_id}", response_model=BookingOut)
async def bookings_get(booking_id: UUID, db: AsyncSession = Depends(get_db)):
    return await get_booking_by_id(db, booking_id)


@router.post("", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
async def bookings_create(
    payload: BookingCreate,
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await create_booking(db, payload)


@router.patch("/{booking_id}", response_model=BookingOut)
async def bookings_update(
    booking_id: UUID,
    payload: BookingUpdate,
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await update_booking(db, booking_id, payload)


@router.post("/{booking_id}/preview", response_model=BookingOut)
async def bookings_upload_preview(
    booking_id: UUID,
    preview: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await upload_booking_preview(db, booking_id, preview)


@router.post("/{booking_id}/images/horizontal", response_model=BookingOut)
async def bookings_add_horizontal_images(
    booking_id: UUID,
    images: list[UploadFile] = File(...),
    sort_order: int = Form(default=0),
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await add_booking_images(
        db,
        booking_id,
        images,
        orientation=BookingImageOrientation.horizontal,
        sort_order=sort_order,
    )


@router.post("/{booking_id}/images/vertical", response_model=BookingOut)
async def bookings_add_vertical_images(
    booking_id: UUID,
    images: list[UploadFile] = File(...),
    sort_order: int = Form(default=0),
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await add_booking_images(
        db,
        booking_id,
        images,
        orientation=BookingImageOrientation.vertical,
        sort_order=sort_order,
    )


@router.delete("/{booking_id}/images/{image_id}", response_model=BookingOut)
async def bookings_delete_image(
    booking_id: UUID,
    image_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await delete_booking_image(db, booking_id, image_id)


@router.delete("/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
async def bookings_delete(
    booking_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    await delete_booking(db, booking_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
