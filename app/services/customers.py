from fastapi import HTTPException, status
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile

from app.models.auth import AuthSubjectType, RefreshSession
from app.models.customer import Customer
from app.models.order import Order
from app.schemas.customer import CustomerUpdate
from app.services.media import delete_local_media_file, save_media_upload


async def update_customer_profile(
    db: AsyncSession,
    customer: Customer,
    payload: CustomerUpdate,
) -> Customer:
    data = payload.model_dump(exclude_unset=True)

    for field in ("name", "email", "birthday"):
        if field in data:
            setattr(customer, field, data[field])

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Customer email is already in use")

    await db.refresh(customer)
    return customer


async def upload_customer_avatar(db: AsyncSession, customer: Customer, file: UploadFile) -> Customer:
    old_avatar_url = customer.avatar_url
    customer.avatar_url = await save_media_upload(file, "customers/avatars", str(customer.id))

    await db.commit()
    delete_local_media_file(old_avatar_url)
    await db.refresh(customer)
    return customer


async def delete_customer_avatar(db: AsyncSession, customer: Customer) -> Customer:
    old_avatar_url = customer.avatar_url
    customer.avatar_url = None

    await db.commit()
    delete_local_media_file(old_avatar_url)
    await db.refresh(customer)
    return customer


async def delete_customer_profile(db: AsyncSession, customer: Customer) -> None:
    old_avatar_url = customer.avatar_url

    await db.execute(
        update(Order)
        .where(Order.customer_id == customer.id)
        .values(customer_id=None)
    )
    await db.execute(
        delete(RefreshSession).where(
            RefreshSession.subject_type == AuthSubjectType.customer,
            RefreshSession.subject_id == customer.id,
        )
    )
    await db.delete(customer)
    await db.commit()

    delete_local_media_file(old_avatar_url)
