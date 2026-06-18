import math
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
import hmac
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.auth import AuthSubjectType, OtpChallenge, OtpRateLimit, RefreshSession
from app.models.base import utcnow
from app.models.customer import Customer
from app.models.staff import StaffUser
from app.security.passwords import verify_password
from app.security.tokens import create_access_token, generate_refresh_token, hash_token, now_utc
from app.services.greensms import GreenSMSError, send_call_verification
from app.services.otp import (
    InvalidPhoneNumberError,
    generate_otp_code,
    hash_otp,
    normalize_phone,
    otp_expires_at,
    print_fake_sms,
    verify_otp,
)


OTP_RATE_LIMIT_PHONE_SCOPE = "phone"
OTP_RATE_LIMIT_IP_SCOPE = "ip"


@dataclass(frozen=True)
class OtpRequestResult:
    retry_after_seconds: int
    resend_available_at: datetime


def normalize_phone_or_422(phone_raw: str) -> str:
    try:
        return normalize_phone(phone_raw)
    except InvalidPhoneNumberError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid phone number")


def seconds_until(moment, current_time) -> int:
    return max(0, math.ceil((moment - current_time).total_seconds()))


def ensure_otp_delivery_provider() -> str:
    provider = settings.otp_delivery_provider.strip().lower()
    if provider in {"console", "dev", "test", "fake", "greensms", "call"}:
        return provider

    raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "OTP delivery provider is not supported")


async def deliver_otp_code(phone: str) -> str:
    provider = ensure_otp_delivery_provider()

    if provider in {"greensms", "call"}:
        try:
            return (await send_call_verification(phone)).code
        except GreenSMSError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "OTP delivery service is unavailable") from exc

    code = generate_otp_code()
    print_fake_sms(phone, code)
    return code


async def get_or_create_otp_rate_limit(
    db: AsyncSession,
    *,
    scope: str,
    key: str,
    current_time,
) -> OtpRateLimit:
    await db.execute(
        pg_insert(OtpRateLimit)
        .values(
            id=uuid4(),
            scope=scope,
            key=key,
            attempts=0,
            window_started_at=current_time,
            created_at=current_time,
            updated_at=current_time,
        )
        .on_conflict_do_nothing(constraint="uq_otp_rate_limits_scope_key")
    )

    rate_limit = await db.scalar(
        select(OtpRateLimit)
        .where(
            OtpRateLimit.scope == scope,
            OtpRateLimit.key == key,
        )
        .with_for_update()
    )

    if not rate_limit:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "OTP rate limit is not available")

    return rate_limit


def reset_rate_limit_window_if_needed(rate_limit: OtpRateLimit, *, current_time, window_seconds: int) -> None:
    if rate_limit.window_started_at + timedelta(seconds=window_seconds) > current_time:
        return

    rate_limit.attempts = 0
    rate_limit.blocked_until = None
    rate_limit.window_started_at = current_time


def validate_refresh_session_context(
    session: RefreshSession,
    *,
    device_id: str,
    ip_address: str | None,
    user_agent: str | None,
) -> None:
    # Bind refresh rotation to a stable client installation, not to volatile IP or user-agent.
    if not session.device_id or not hmac.compare_digest(session.device_id, device_id):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")

    session.ip_address = ip_address
    session.user_agent = user_agent


async def request_customer_otp(db: AsyncSession, phone_raw: str, *, ip_address: str | None) -> OtpRequestResult:
    phone = normalize_phone_or_422(phone_raw)
    current_time = now_utc()

    phone_rate_limit = await get_or_create_otp_rate_limit(
        db,
        scope=OTP_RATE_LIMIT_PHONE_SCOPE,
        key=phone,
        current_time=current_time,
    )
    reset_rate_limit_window_if_needed(
        phone_rate_limit,
        current_time=current_time,
        window_seconds=settings.otp_phone_window_seconds,
    )

    ip_rate_limit = None
    if ip_address:
        ip_rate_limit = await get_or_create_otp_rate_limit(
            db,
            scope=OTP_RATE_LIMIT_IP_SCOPE,
            key=ip_address,
            current_time=current_time,
        )
        reset_rate_limit_window_if_needed(
            ip_rate_limit,
            current_time=current_time,
            window_seconds=settings.otp_ip_window_seconds,
        )

    blocked_until_values = [
        rate_limit.blocked_until
        for rate_limit in (phone_rate_limit, ip_rate_limit)
        if rate_limit and rate_limit.blocked_until and rate_limit.blocked_until > current_time
    ]

    active = await db.scalar(
        select(OtpChallenge)
        .where(
            OtpChallenge.phone == phone,
            OtpChallenge.consumed_at.is_(None),
            OtpChallenge.expires_at > now_utc(),
        )
        .order_by(OtpChallenge.created_at.desc())
    )

    if active and active.resend_available_at > current_time:
        blocked_until_values.append(active.resend_available_at)

    if blocked_until_values:
        resend_available_at = max(blocked_until_values)
        return OtpRequestResult(
            retry_after_seconds=seconds_until(resend_available_at, current_time),
            resend_available_at=resend_available_at,
        )

    if phone_rate_limit.attempts >= settings.otp_phone_max_requests_per_window:
        resend_available_at = phone_rate_limit.window_started_at + timedelta(seconds=settings.otp_phone_window_seconds)
        phone_rate_limit.blocked_until = resend_available_at
        await db.commit()
        return OtpRequestResult(
            retry_after_seconds=seconds_until(resend_available_at, current_time),
            resend_available_at=resend_available_at,
        )

    phone_rate_limit.attempts += 1
    if phone_rate_limit.attempts >= settings.otp_phone_max_requests_per_window:
        phone_rate_limit.blocked_until = phone_rate_limit.window_started_at + timedelta(
            seconds=settings.otp_phone_window_seconds
        )
    else:
        phone_rate_limit.blocked_until = current_time + timedelta(seconds=settings.otp_resend_cooldown_seconds)

    if ip_rate_limit:
        ip_rate_limit.attempts += 1
        if ip_rate_limit.attempts >= settings.otp_ip_max_requests_per_window:
            ip_rate_limit.blocked_until = current_time + timedelta(seconds=settings.otp_ip_window_seconds)
        else:
            ip_rate_limit.blocked_until = current_time + timedelta(seconds=settings.otp_global_cooldown_seconds)

    code = await deliver_otp_code(phone)
    resend_available_at = max(
        rate_limit.blocked_until
        for rate_limit in (phone_rate_limit, ip_rate_limit)
        if rate_limit and rate_limit.blocked_until
    )
    db.add(
        OtpChallenge(
            phone=phone,
            code_hash=hash_otp(phone, code),
            attempts_left=settings.otp_max_attempts,
            expires_at=otp_expires_at(),
            resend_available_at=resend_available_at,
        )
    )
    await db.commit()

    return OtpRequestResult(
        retry_after_seconds=seconds_until(resend_available_at, current_time),
        resend_available_at=resend_available_at,
    )


async def verify_customer_otp_and_issue_tokens(
    db: AsyncSession,
    *,
    phone_raw: str,
    code: str,
    device_id: str,
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
        .with_for_update()
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
    device_id: str,
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
    device_id: str,
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
    device_id: str,
    device_name: str | None,
    ip_address: str | None,
    user_agent: str | None,
):
    session = await db.scalar(
        select(RefreshSession)
        .where(
            RefreshSession.token_hash == hash_token(refresh_token),
            RefreshSession.revoked_at.is_(None),
            RefreshSession.expires_at > now_utc(),
        )
        .with_for_update()
    )

    if not session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")

    validate_refresh_session_context(
        session,
        device_id=device_id,
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
        device_name=device_name or session.device_name,
        ip_address=session.ip_address,
        user_agent=session.user_agent,
    )
    await db.commit()

    return tokens, subject, session.subject_type


async def logout_refresh_session(
    db: AsyncSession,
    *,
    refresh_token: str,
    device_id: str,
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
