from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.api.deps import get_token_payload
from app.db.session import get_db
from app.models.auth import AuthSubjectType
from app.schemas.auth import (
    AuthSubjectOut,
    CustomerOtpRequest,
    CustomerOtpVerify,
    LogoutRequest,
    LogoutResponse,
    OtpRequested,
    RefreshRequest,
    StaffLogin,
    TokenPair,
)
from app.services.auth import (
    logout_all_refresh_sessions,
    logout_refresh_session,
    request_customer_otp,
    rotate_refresh_token,
    staff_login_and_issue_tokens,
    verify_customer_otp_and_issue_tokens,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def client_meta(request: Request):
    return request.client.host if request.client else None, request.headers.get("user-agent")


def refresh_token_from_request(request: Request, token: str | None) -> str:
    refresh_token = token or request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token is required")

    return refresh_token


def build_subject_out(subject, subject_type: AuthSubjectType) -> AuthSubjectOut:
    if subject_type == AuthSubjectType.customer:
        return AuthSubjectOut(
            id=subject.id,
            subject_type=AuthSubjectType.customer.value,
            phone=subject.phone,
            name=subject.name,
            email=subject.email,
            birthday=subject.birthday,
            avatar_url=subject.avatar_url,
        )

    return AuthSubjectOut(
        id=subject.id,
        subject_type=AuthSubjectType.staff.value,
        phone=subject.phone,
        email=subject.email,
        role=subject.role.value,
    )


def to_response(response: Response, access_token: str, refresh_token: str, user: AuthSubjectOut) -> TokenPair:
    response.set_cookie(
        "refresh_token",
        refresh_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.refresh_token_days * 24 * 60 * 60,
        path="/api/v1/auth",
    )
    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_minutes * 60,
        user=user,
    )


def delete_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        "refresh_token",
        path="/api/v1/auth",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )


@router.post("/customer/otp/request", response_model=OtpRequested)
async def customer_otp_request(payload: CustomerOtpRequest, request: Request, db: AsyncSession = Depends(get_db)):
    ip, _ = client_meta(request)
    result = await request_customer_otp(db, payload.phone, ip_address=ip)
    return OtpRequested(
        retry_after_seconds=result.retry_after_seconds,
        resend_available_at=result.resend_available_at,
    )


@router.post("/customer/otp/verify", response_model=TokenPair, response_model_exclude_none=True)
async def customer_otp_verify(payload: CustomerOtpVerify, request: Request, response: Response,
                              db: AsyncSession = Depends(get_db)):
    ip, ua = client_meta(request)
    tokens, customer = await verify_customer_otp_and_issue_tokens(
        db,
        phone_raw=payload.phone,
        code=payload.code,
        device_id=payload.device_id,
        device_name=payload.device_name,
        ip_address=ip,
        user_agent=ua,
    )
    access_token, refresh_token = tokens
    user = build_subject_out(customer, AuthSubjectType.customer)
    return to_response(response, access_token, refresh_token, user)


@router.post("/staff/login", response_model=TokenPair, response_model_exclude_none=True)
async def staff_login(payload: StaffLogin, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    ip, ua = client_meta(request)
    tokens, staff = await staff_login_and_issue_tokens(
        db,
        email=str(payload.email).lower(),
        password=payload.password,
        device_id=payload.device_id,
        device_name=payload.device_name,
        ip_address=ip,
        user_agent=ua,
    )
    access_token, refresh_token = tokens
    user = build_subject_out(staff, AuthSubjectType.staff)
    return to_response(response, access_token, refresh_token, user)


@router.post("/refresh", response_model=TokenPair, response_model_exclude_none=True)
async def refresh(payload: RefreshRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    ip, ua = client_meta(request)
    tokens, subject, subject_type = await rotate_refresh_token(
        db,
        refresh_token=refresh_token_from_request(request, payload.refresh_token),
        device_id=payload.device_id,
        device_name=payload.device_name,
        ip_address=ip,
        user_agent=ua,
    )
    access_token, refresh_token = tokens
    user = build_subject_out(subject, subject_type)
    return to_response(response, access_token, refresh_token, user)


@router.post("/logout", response_model=LogoutResponse)
async def logout(payload: LogoutRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    ip, ua = client_meta(request)
    await logout_refresh_session(
        db,
        refresh_token=refresh_token_from_request(request, payload.refresh_token),
        device_id=payload.device_id,
        ip_address=ip,
        user_agent=ua,
    )
    delete_refresh_cookie(response)
    return LogoutResponse()


@router.post("/logout/all", response_model=LogoutResponse)
async def logout_all(
    response: Response,
    payload: dict = Depends(get_token_payload),
    db: AsyncSession = Depends(get_db),
):
    await logout_all_refresh_sessions(
        db,
        subject_type=AuthSubjectType(payload["subject_type"]),
        subject_id=UUID(payload["sub"]),
    )
    delete_refresh_cookie(response)
    return LogoutResponse()
