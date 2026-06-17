from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_customer
from app.core.config import settings
from app.db.session import get_db
from app.models.customer import Customer
from app.schemas.customer import CustomerOut, CustomerUpdate
from app.services.customers import (
    delete_customer_avatar,
    delete_customer_profile,
    update_customer_profile,
    upload_customer_avatar,
)

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("/me", response_model=CustomerOut)
async def customers_me(customer: Customer = Depends(get_current_customer)):
    return customer


@router.patch("/me", response_model=CustomerOut)
async def customers_update_me(
    payload: CustomerUpdate,
    db: AsyncSession = Depends(get_db),
    customer: Customer = Depends(get_current_customer),
):
    return await update_customer_profile(db, customer, payload)


@router.post("/me/avatar", response_model=CustomerOut)
async def customers_upload_avatar(
    avatar: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    customer: Customer = Depends(get_current_customer),
):
    return await upload_customer_avatar(db, customer, avatar)


@router.delete("/me/avatar", status_code=status.HTTP_204_NO_CONTENT)
async def customers_delete_avatar(
    db: AsyncSession = Depends(get_db),
    customer: Customer = Depends(get_current_customer),
):
    await delete_customer_avatar(db, customer)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def customers_delete_me(
    db: AsyncSession = Depends(get_db),
    customer: Customer = Depends(get_current_customer),
):
    await delete_customer_profile(db, customer)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        "refresh_token",
        path="/api/v1/auth",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response
