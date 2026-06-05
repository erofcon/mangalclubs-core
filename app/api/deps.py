from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.customer import Customer
from app.models.staff import StaffRole, StaffUser
from app.security.tokens import decode_token

bearer = HTTPBearer(auto_error=False)


async def get_token_payload(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    try:
        payload = decode_token(creds.credentials)
        if payload.get("typ") != "access":
            raise ValueError
        return payload
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")


async def get_current_customer(
    payload: dict = Depends(get_token_payload),
    db: AsyncSession = Depends(get_db),
) -> Customer:
    if payload.get("subject_type") != "customer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Customer only")

    customer = await db.get(Customer, UUID(payload["sub"]))
    if not customer or not customer.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

    return customer


async def get_current_staff(
    payload: dict = Depends(get_token_payload),
    db: AsyncSession = Depends(get_db),
) -> StaffUser:
    if payload.get("subject_type") != "staff":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Staff only")

    staff = await db.get(StaffUser, UUID(payload["sub"]))
    if not staff or not staff.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

    return staff


async def get_current_admin(staff: StaffUser = Depends(get_current_staff)) -> StaffUser:
    if staff.role != StaffRole.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")

    return staff
