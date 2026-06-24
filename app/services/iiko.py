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
from app.services.availability import get_organization_orders_availability


logger = logging.getLogger(__name__)


class IikoAuthorizationError(Exception):
    pass


class IikoTerminalError(Exception):
    pass


ORDERS_AVAILABLE_MESSAGE = "Сейчас можно оформить онлайн-заказ."
ORDERS_UNAVAILABLE_MESSAGE = "Сейчас онлайн-заказы временно недоступны. Пожалуйста, попробуйте позже."
TERMINAL_UNAVAILABLE_MESSAGE = "Сейчас онлайн-заказы временно недоступны. Пожалуйста, попробуйте позже."


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


def build_iiko_availability(
    organization: Organization,
    *,
    orders_available: bool,
    iiko_status: str,
    reason: str,
    message: str,
) -> dict:
    return {
        "organization_id": organization.id,
        "slug": organization.slug,
        "orders_available": orders_available,
        "iiko_status": iiko_status,
        "reason": reason,
        "message": message,
        "checked_at": utcnow(),
    }


async def get_iiko_availability(db: AsyncSession, organization: Organization) -> dict:
    if not organization.iiko_api_login or not organization.iiko_organization_id:
        return build_iiko_availability(
            organization,
            orders_available=False,
            iiko_status="not_configured",
            reason="iiko_not_configured",
            message=ORDERS_UNAVAILABLE_MESSAGE,
        )

    try:
        access_token = await get_valid_token(db, organization.id)
    except IikoAuthorizationError:
        return build_iiko_availability(
            organization,
            orders_available=False,
            iiko_status="unavailable",
            reason="iiko_unavailable",
            message=ORDERS_UNAVAILABLE_MESSAGE,
        )

    try:
        await get_alive_iiko_terminal_group_id(access_token, organization.iiko_organization_id)
    except IikoTerminalError:
        return build_iiko_availability(
            organization,
            orders_available=False,
            iiko_status="terminal_unavailable",
            reason="iiko_terminal_unavailable",
            message=TERMINAL_UNAVAILABLE_MESSAGE,
        )

    working_hours_availability = get_organization_orders_availability(organization)
    if not working_hours_availability["orders_available"]:
        return build_iiko_availability(
            organization,
            orders_available=False,
            iiko_status="connected",
            reason=working_hours_availability["reason"],
            message=working_hours_availability["message"],
        )

    return build_iiko_availability(
        organization,
        orders_available=True,
        iiko_status="connected",
        reason="iiko_connected",
        message=ORDERS_AVAILABLE_MESSAGE,
    )


async def request_iiko_json(path: str, access_token: str, *, json_body: dict | None) -> dict:
    url = f"{settings.iiko_api_base_url.rstrip('/')}{path}"
    headers = {"Authorization": f"Bearer {access_token}"}
    timeout = httpx.Timeout(settings.iiko_request_timeout_seconds)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=json_body)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:500]
        raise IikoTerminalError(f"iiko request failed with HTTP {exc.response.status_code}: {body}") from exc
    except httpx.HTTPError as exc:
        raise IikoTerminalError(f"iiko request failed: {exc}") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise IikoTerminalError("iiko returned a non-JSON response") from exc

    if not isinstance(data, dict):
        raise IikoTerminalError("iiko returned an invalid response")

    return data


async def request_iiko_terminal_groups(access_token: str, iiko_organization_id: str) -> list[str]:
    data = await request_iiko_json(
        "/api/1/terminal_groups",
        access_token,
        json_body={"organizationIds": [iiko_organization_id]},
    )
    terminal_groups = data.get("terminalGroups")
    if not isinstance(terminal_groups, list):
        raise IikoTerminalError("iiko terminal groups response does not contain terminalGroups")

    terminal_group_ids: list[str] = []
    for organization_group in terminal_groups:
        if not isinstance(organization_group, dict):
            continue
        if organization_group.get("organizationId") != iiko_organization_id:
            continue

        items = organization_group.get("items")
        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict):
                continue
            terminal_group_id = item.get("id")
            if isinstance(terminal_group_id, str) and terminal_group_id:
                terminal_group_ids.append(terminal_group_id)

    if not terminal_group_ids:
        raise IikoTerminalError("iiko returned no terminal groups")

    return terminal_group_ids


async def get_alive_iiko_terminal_group_id(access_token: str, iiko_organization_id: str) -> str:
    terminal_group_ids = await request_iiko_terminal_groups(access_token, iiko_organization_id)
    data = await request_iiko_json(
        "/api/1/terminal_groups/is_alive",
        access_token,
        json_body={
            "organizationIds": [iiko_organization_id],
            "terminalGroupIds": terminal_group_ids,
        },
    )
    statuses = data.get("isAliveStatus")
    if not isinstance(statuses, list):
        raise IikoTerminalError("iiko terminal status response does not contain isAliveStatus")

    for terminal_status in statuses:
        if not isinstance(terminal_status, dict):
            continue
        if terminal_status.get("organizationId") != iiko_organization_id:
            continue
        terminal_group_id = terminal_status.get("terminalGroupId")
        if terminal_status.get("isAlive") is True and isinstance(terminal_group_id, str) and terminal_group_id:
            return terminal_group_id

    raise IikoTerminalError("iiko terminal is not alive")


async def request_iiko_access_token(api_key: str) -> tuple[str, str | None, datetime]:
    if not settings.iiko_app_id or not settings.iiko_client_secret:
        raise IikoAuthorizationError("iiko v2 auth requires IIKO_APP_ID and IIKO_CLIENT_SECRET")

    url = f"{settings.iiko_api_base_url.rstrip('/')}/api/v2/access_token"
    timeout = httpx.Timeout(settings.iiko_request_timeout_seconds)
    payload = {
        "apiKey": api_key,
        "appId": settings.iiko_app_id,
        "clientSecret": settings.iiko_client_secret,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
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


async def invalidate_iiko_token(db: AsyncSession, organization_id: UUID, reason: str) -> None:
    token = await db.scalar(select(IikoToken).where(IikoToken.organization_id == organization_id))
    if token is None:
        return

    token.access_token = None
    token.correlation_id = None
    token.expires_at = None
    token.last_error = reason
    await db.commit()


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
        raise IikoAuthorizationError("Organization does not have iiko api key")

    if should_refresh(organization.iiko_token):
        token = await authorize_organization(db, organization)
    else:
        token = organization.iiko_token

    if not token or not token.access_token or should_refresh(token):
        raise IikoAuthorizationError(token.last_error if token and token.last_error else "iiko token is not available")

    return token.access_token


async def get_organization_availability_by_slug(db: AsyncSession, slug: str) -> dict:
    organization = await db.scalar(
        select(Organization)
        .options(selectinload(Organization.iiko_token), selectinload(Organization.working_hours))
        .where(Organization.slug == slug)
    )
    if not organization:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заведение не найдено.")

    return await get_iiko_availability(db, organization)


async def ensure_iiko_orders_available(db: AsyncSession, organization_id: UUID) -> str:
    try:
        access_token = await get_valid_token(db, organization_id)
        organization = await db.get(Organization, organization_id)
        if not organization or not organization.iiko_organization_id:
            raise IikoTerminalError("Organization does not have iiko organization id")
        await get_alive_iiko_terminal_group_id(access_token, organization.iiko_organization_id)
        return access_token
    except IikoTerminalError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            TERMINAL_UNAVAILABLE_MESSAGE,
        )
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
                    Organization.accepts_pickup.is_(True),
                    Organization.accepts_delivery.is_(True),
                ),
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
