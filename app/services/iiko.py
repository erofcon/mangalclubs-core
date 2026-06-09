from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
import jwt
from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.base import utcnow
from app.models.organization import IikoToken, Organization


logger = logging.getLogger(__name__)


class IikoAuthorizationError(Exception):
    pass


ORDERS_AVAILABLE_MESSAGE = "Онлайн-заказы доступны"
ORDERS_UNAVAILABLE_MESSAGE = "Онлайн-заказы временно недоступны"


def token_refresh_deadline() -> datetime:
    return utcnow() + timedelta(seconds=settings.iiko_token_refresh_margin_seconds)


def decode_token_expires_at(access_token: str) -> datetime:
    try:
        payload = jwt.decode(access_token, options={"verify_signature": False, "verify_aud": False})
    except jwt.PyJWTError as exc:
        raise IikoAuthorizationError("iiko returned an invalid JWT token") from exc

    expires_at = payload.get("exp")
    if not isinstance(expires_at, int):
        raise IikoAuthorizationError("iiko token does not contain exp")

    return datetime.fromtimestamp(expires_at, tz=timezone.utc)


def should_refresh(token: IikoToken | None) -> bool:
    if not token or not token.access_token or not token.expires_at:
        return True

    return token.expires_at <= token_refresh_deadline()


def get_iiko_availability(organization: Organization) -> dict:
    checked_at = utcnow()

    if not organization.iiko_api_login:
        return {
            "organization_id": organization.id,
            "slug": organization.slug,
            "orders_available": False,
            "iiko_status": "not_configured",
            "reason": "iiko_not_configured",
            "message": ORDERS_UNAVAILABLE_MESSAGE,
            "checked_at": checked_at,
        }

    token = organization.iiko_token
    if token and token.access_token and token.expires_at and token.expires_at > checked_at:
        if should_refresh(token):
            return {
                "organization_id": organization.id,
                "slug": organization.slug,
                "orders_available": True,
                "iiko_status": "refreshing",
                "reason": "iiko_refreshing",
                "message": ORDERS_AVAILABLE_MESSAGE,
                "checked_at": checked_at,
            }

        return {
            "organization_id": organization.id,
            "slug": organization.slug,
            "orders_available": True,
            "iiko_status": "connected",
            "reason": "iiko_connected",
            "message": ORDERS_AVAILABLE_MESSAGE,
            "checked_at": checked_at,
        }

    return {
        "organization_id": organization.id,
        "slug": organization.slug,
        "orders_available": False,
        "iiko_status": "unavailable",
        "reason": "iiko_unavailable",
        "message": ORDERS_UNAVAILABLE_MESSAGE,
        "checked_at": checked_at,
    }


async def request_iiko_access_token(api_login: str) -> tuple[str, str | None, datetime]:
    url = f"{settings.iiko_api_base_url.rstrip('/')}/api/1/access_token"
    timeout = httpx.Timeout(settings.iiko_request_timeout_seconds)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json={"apiLogin": api_login})
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:500]
        raise IikoAuthorizationError(f"iiko auth failed with HTTP {exc.response.status_code}: {body}") from exc
    except httpx.HTTPError as exc:
        raise IikoAuthorizationError(f"iiko auth request failed: {exc}") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise IikoAuthorizationError("iiko returned a non-JSON auth response") from exc

    access_token = data.get("token")
    if not isinstance(access_token, str) or not access_token:
        raise IikoAuthorizationError("iiko auth response does not contain token")

    correlation_id = data.get("correlationId")
    if correlation_id is not None and not isinstance(correlation_id, str):
        correlation_id = str(correlation_id)

    return access_token, correlation_id, decode_token_expires_at(access_token)


async def get_or_create_iiko_token(db: AsyncSession, organization_id: UUID) -> IikoToken:
    token = await db.scalar(select(IikoToken).where(IikoToken.organization_id == organization_id))
    if token:
        return token

    token = IikoToken(organization_id=organization_id)
    db.add(token)
    await db.flush()
    return token


async def authorize_organization(db: AsyncSession, organization: Organization) -> IikoToken | None:
    if not organization.iiko_api_login:
        return None

    token = await get_or_create_iiko_token(db, organization.id)

    try:
        access_token, correlation_id, expires_at = await request_iiko_access_token(organization.iiko_api_login)
    except IikoAuthorizationError as exc:
        token.access_token = None
        token.correlation_id = None
        token.expires_at = None
        token.last_error = str(exc)
        await db.commit()
        logger.warning("iiko authorization failed for organization %s: %s", organization.id, exc)
        return token

    token.access_token = access_token
    token.correlation_id = correlation_id
    token.expires_at = expires_at
    token.last_authorized_at = utcnow()
    token.last_error = None
    await db.commit()
    return token


async def get_valid_token(db: AsyncSession, organization_id: UUID) -> str:
    organization = await db.scalar(
        select(Organization)
        .options(selectinload(Organization.iiko_token))
        .where(Organization.id == organization_id)
        .with_for_update()
    )
    if not organization:
        raise IikoAuthorizationError("Organization not found")

    if not organization.iiko_api_login:
        raise IikoAuthorizationError("Organization does not have iiko apiLogin")

    if should_refresh(organization.iiko_token):
        token = await authorize_organization(db, organization)
    else:
        token = organization.iiko_token

    if not token or not token.access_token or should_refresh(token):
        raise IikoAuthorizationError(token.last_error if token and token.last_error else "iiko token is not available")

    return token.access_token


async def get_organization_availability_by_slug(db: AsyncSession, slug: str) -> dict:
    organization = await db.scalar(
        select(Organization).options(selectinload(Organization.iiko_token)).where(Organization.slug == slug)
    )
    if not organization:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")

    return get_iiko_availability(organization)


async def ensure_iiko_orders_available(db: AsyncSession, organization_id: UUID) -> str:
    try:
        return await get_valid_token(db, organization_id)
    except IikoAuthorizationError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ORDERS_UNAVAILABLE_MESSAGE,
        )


async def refresh_iiko_tokens_once() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.scalars(
            select(Organization)
            .outerjoin(Organization.iiko_token)
            .options(selectinload(Organization.iiko_token))
            .where(
                Organization.iiko_api_login.is_not(None),
                or_(
                    IikoToken.id.is_(None),
                    IikoToken.access_token.is_(None),
                    IikoToken.expires_at.is_(None),
                    IikoToken.expires_at <= token_refresh_deadline(),
                ),
            )
            .order_by(Organization.name)
        )
        organizations = list(result.unique())

        for organization in organizations:
            await authorize_organization(db, organization)


async def run_iiko_token_refresher(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await refresh_iiko_tokens_once()
        except Exception:
            logger.exception("Unexpected error while refreshing iiko tokens")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.iiko_auth_poll_seconds)
        except asyncio.TimeoutError:
            pass
