from datetime import timedelta
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.auth import AuthSubjectType, OtpChallenge, RefreshSession
from app.models.base import utcnow
from app.models.customer import Customer
from app.models.staff import StaffUser
from app.security.passwords import verify_password
from app.security.tokens import create_access_token, generate_refresh_token, hash_token, now_utc
from app.services.otp import (
    InvalidPhoneNumberError,
    generate_otp_code,
    hash_otp,
    normalize_phone,
    otp_expires_at,
    otp_resend_available_at,
    print_fake_sms,
    verify_otp,
)


def normalize_phone_or_422(phone_raw: str) -> str:
    try:
        return normalize_phone(phone_raw)
    except InvalidPhoneNumberError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid phone number")


def validate_refresh_session_context(
    session: RefreshSession,
    *,
    device_id: str | None,
    device_name: str | None,
    ip_address: str | None,
    user_agent: str | None,
) -> None:
    checks = (
        (session.device_id, device_id),
        (session.device_name, device_name),
        (session.ip_address, ip_address),
        (session.user_agent, user_agent),
    )

    # Refresh-токен должен обновляться из той же клиентской сессии, где был выдан.
    if any(expected and expected != actual for expected, actual in checks):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")


async def request_customer_otp(db: AsyncSession, phone_raw: str) -> None:
    phone = normalize_phone_or_422(phone_raw)

    active = await db.scalar(
        select(OtpChallenge)
        .where(
            OtpChallenge.phone == phone,
            OtpChallenge.consumed_at.is_(None),
            OtpChallenge.expires_at > now_utc(),
        )
        .order_by(OtpChallenge.created_at.desc())
    )

    if active and active.resend_available_at > now_utc():
        return

    code = generate_otp_code()
    db.add(
        OtpChallenge(
            phone=phone,
            code_hash=hash_otp(phone, code),
            attempts_left=settings.otp_max_attempts,
            expires_at=otp_expires_at(),
            resend_available_at=otp_resend_available_at(),
        )
    )
    await db.commit()

    print_fake_sms(phone, code)


async def verify_customer_otp_and_issue_tokens(
    db: AsyncSession,
    *,
    phone_raw: str,
    code: str,
    device_id: str | None,
    device_name: str | None,
    ip_address: str | None,
    user_agent: str | None,
):
    phone = normalize_phone_or_422(phone_raw)

    challenge = await db.scalar(
        select(OtpChallenge)
        .where(
            OtpChallenge.phone == phone,
            OtpChallenge.consumed_at.is_(None),
            OtpChallenge.expires_at > now_utc(),
        )
        .order_by(OtpChallenge.created_at.desc())
    )

    if not challenge or challenge.attempts_left <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired code")

    if not verify_otp(phone, code, challenge.code_hash):
        challenge.attempts_left -= 1
        await db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired code")

    challenge.consumed_at = utcnow()

    customer = await db.scalar(select(Customer).where(Customer.phone == phone))
    if not customer:
        customer = Customer(phone=phone, is_active=True)
        db.add(customer)
        await db.flush()

    tokens = await issue_tokens(
        db,
        subject_id=customer.id,
        subject_type=AuthSubjectType.customer,
        role=None,
        device_id=device_id,
        device_name=device_name,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()

    return tokens, customer


async def staff_login_and_issue_tokens(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    device_id: str | None,
    device_name: str | None,
    ip_address: str | None,
    user_agent: str | None,
):
    staff = await db.scalar(select(StaffUser).where(StaffUser.email == email.lower()))

    if not staff or not verify_password(password, staff.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")

    if not staff.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User is inactive")

    tokens = await issue_tokens(
        db,
        subject_id=staff.id,
        subject_type=AuthSubjectType.staff,
        role=staff.role.value,
        device_id=device_id,
        device_name=device_name,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()

    return tokens, staff


async def issue_tokens(
    db: AsyncSession,
    *,
    subject_id,
    subject_type: AuthSubjectType,
    role: str | None,
    device_id: str | None,
    device_name: str | None,
    ip_address: str | None,
    user_agent: str | None,
):
    refresh_token = generate_refresh_token()

    db.add(
        RefreshSession(
            subject_type=subject_type,
            subject_id=subject_id,
            token_hash=hash_token(refresh_token),
            device_id=device_id,
            device_name=device_name,
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=now_utc() + timedelta(days=settings.refresh_token_days),
        )
    )

    access_token = create_access_token(
        subject_id=subject_id,
        subject_type=subject_type.value,
        role=role,
    )

    return access_token, refresh_token


async def rotate_refresh_token(
    db: AsyncSession,
    *,
    refresh_token: str,
    device_id: str | None,
    device_name: str | None,
    ip_address: str | None,
    user_agent: str | None,
):
    session = await db.scalar(
        select(RefreshSession).where(
            RefreshSession.token_hash == hash_token(refresh_token),
            RefreshSession.revoked_at.is_(None),
            RefreshSession.expires_at > now_utc(),
        )
    )

    if not session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")

    validate_refresh_session_context(
        session,
        device_id=device_id,
        device_name=device_name,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    if session.subject_type == AuthSubjectType.customer:
        subject = await db.get(Customer, session.subject_id)
        role = None
    else:
        subject = await db.get(StaffUser, session.subject_id)
        role = subject.role.value if subject else None

    if not subject or not subject.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")

    session.revoked_at = utcnow()

    tokens = await issue_tokens(
        db,
        subject_id=subject.id,
        subject_type=session.subject_type,
        role=role,
        device_id=session.device_id,
        device_name=session.device_name,
        ip_address=session.ip_address,
        user_agent=session.user_agent,
    )
    await db.commit()

    return tokens, subject, session.subject_type


async def logout_refresh_session(
    db: AsyncSession,
    *,
    refresh_token: str,
    device_id: str | None,
    device_name: str | None,
    ip_address: str | None,
    user_agent: str | None,
) -> None:
    session = await db.scalar(
        select(RefreshSession).where(
            RefreshSession.token_hash == hash_token(refresh_token),
            RefreshSession.revoked_at.is_(None),
        )
    )

    if not session:
        return

    validate_refresh_session_context(
        session,
        device_id=device_id,
        device_name=device_name,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    session.revoked_at = utcnow()
    await db.commit()


async def logout_all_refresh_sessions(
    db: AsyncSession,
    *,
    subject_type: AuthSubjectType,
    subject_id: UUID,
) -> None:
    await db.execute(
        update(RefreshSession)
        .where(
            RefreshSession.subject_type == subject_type,
            RefreshSession.subject_id == subject_id,
            RefreshSession.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow())
    )
    await db.commit()
