from __future__ import annotations

import asyncio
import logging
from uuid import UUID

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.datastructures import UploadFile

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.base import utcnow
from app.models.menu import IikoMenuSnapshot, MenuItemContent
from app.models.organization import Organization
from app.schemas.menu import MenuItemContentCreate, MenuItemContentUpdate, OrderType
from app.services.iiko import IikoAuthorizationError, get_valid_token
from app.services.media import delete_local_media_file, save_media_upload


logger = logging.getLogger(__name__)

MENU_UNAVAILABLE_MESSAGE = "Menu is temporarily unavailable"


class IikoMenuError(Exception):
    pass


async def request_iiko_external_menus(access_token: str) -> list[dict]:
    data = await request_iiko_json(
        "/api/2/menu",
        access_token,
        json_body=None,
    )
    external_menus = data.get("externalMenus")
    if not isinstance(external_menus, list):
        raise IikoMenuError("iiko menu list response does not contain externalMenus")

    return [item for item in external_menus if isinstance(item, dict)]


async def request_iiko_menu_by_id(access_token: str, external_menu_id: str, iiko_organization_id: str) -> dict:
    return await request_iiko_json(
        "/api/2/menu/by_id",
        access_token,
        json_body={
            "externalMenuId": external_menu_id,
            "organizationIds": [iiko_organization_id],
        },
    )


async def request_iiko_json(path: str, access_token: str, *, json_body: dict | None) -> dict:
    url = f"{settings.iiko_api_base_url.rstrip('/')}{path}"
    headers = {"Authorization": f"Bearer {access_token}"}
    timeout = httpx.Timeout(settings.iiko_request_timeout_seconds)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if json_body is None:
                response = await client.post(url, headers=headers)
            else:
                response = await client.post(url, headers=headers, json=json_body)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:500]
        raise IikoMenuError(f"iiko menu request failed with HTTP {exc.response.status_code}: {body}") from exc
    except httpx.HTTPError as exc:
        raise IikoMenuError(f"iiko menu request failed: {exc}") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise IikoMenuError("iiko returned a non-JSON menu response") from exc

    if not isinstance(data, dict):
        raise IikoMenuError("iiko returned an invalid menu response")

    return data


async def sync_iiko_menu_for_organization(db: AsyncSession, organization: Organization) -> IikoMenuSnapshot:
    organization_id = organization.id
    iiko_organization_id = organization.iiko_organization_id
    snapshot = await get_or_create_menu_snapshot(db, organization_id)

    if not iiko_organization_id:
        snapshot.last_error = "Organization does not have iiko organization id"
        await db.commit()
        raise IikoMenuError(snapshot.last_error)

    try:
        access_token = await get_valid_token(db, organization_id)
        external_menu = await get_first_external_menu(access_token)
        raw_menu = await request_iiko_menu_by_id(access_token, external_menu["id"], iiko_organization_id)
    except (IikoAuthorizationError, IikoMenuError) as exc:
        snapshot.last_error = str(exc)
        await db.commit()
        raise IikoMenuError(str(exc)) from exc

    snapshot.external_menu_id = external_menu["id"]
    snapshot.external_menu_name = external_menu.get("name")
    snapshot.revision = parse_int(raw_menu.get("revision"))
    snapshot.raw_menu = raw_menu
    snapshot.synced_at = utcnow()
    snapshot.last_error = None
    await db.commit()
    await db.refresh(snapshot)
    return snapshot


async def get_first_external_menu(access_token: str) -> dict[str, str | None]:
    external_menus = await request_iiko_external_menus(access_token)
    if not external_menus:
        raise IikoMenuError("iiko returned no external menus")

    external_menu = external_menus[0]
    external_menu_id = external_menu.get("id")
    if external_menu_id is None:
        raise IikoMenuError("iiko external menu does not contain id")

    external_menu_name = external_menu.get("name")
    return {
        "id": str(external_menu_id),
        "name": str(external_menu_name) if external_menu_name is not None else None,
    }


async def get_or_create_menu_snapshot(db: AsyncSession, organization_id: UUID) -> IikoMenuSnapshot:
    snapshot = await db.scalar(select(IikoMenuSnapshot).where(IikoMenuSnapshot.organization_id == organization_id))
    if snapshot:
        return snapshot

    await db.execute(
        insert(IikoMenuSnapshot)
        .values(
            organization_id=organization_id,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        .on_conflict_do_nothing(index_elements=[IikoMenuSnapshot.organization_id])
    )
    snapshot = await db.scalar(select(IikoMenuSnapshot).where(IikoMenuSnapshot.organization_id == organization_id))
    if snapshot:
        return snapshot

    raise IikoMenuError("Could not create iiko menu snapshot")


async def get_menu(
    db: AsyncSession,
    *,
    order_type: OrderType,
    organization_id: UUID | None = None,
    organization_slug: str | None = None,
    refresh: bool = False,
) -> dict:
    organization = await resolve_menu_organization(
        db,
        order_type=order_type,
        organization_id=organization_id,
        organization_slug=organization_slug,
    )

    snapshot = organization.iiko_menu_snapshot
    sync_failed = False
    if refresh or not snapshot or not snapshot.raw_menu:
        try:
            snapshot = await sync_iiko_menu_for_organization(db, organization)
        except IikoMenuError as exc:
            sync_failed = True
            logger.warning("iiko menu sync failed for organization %s: %s", organization.id, exc)
            await db.refresh(organization, attribute_names=["iiko_menu_snapshot"])
            snapshot = organization.iiko_menu_snapshot

    if not snapshot or not snapshot.raw_menu:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, MENU_UNAVAILABLE_MESSAGE)

    contents = await list_menu_item_contents(db, active_only=True)
    return build_menu_response(
        organization,
        snapshot,
        contents,
        order_type=order_type,
        is_stale=sync_failed,
    )


async def get_organization_menu(
    db: AsyncSession,
    organization: Organization,
    *,
    order_type: OrderType,
    is_stale: bool = False,
) -> dict:
    await db.refresh(organization, attribute_names=["iiko_menu_snapshot"])
    snapshot = organization.iiko_menu_snapshot
    if not snapshot or not snapshot.raw_menu:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, MENU_UNAVAILABLE_MESSAGE)

    contents = await list_menu_item_contents(db, active_only=True)
    return build_menu_response(
        organization,
        snapshot,
        contents,
        order_type=order_type,
        is_stale=is_stale,
    )


async def resolve_menu_organization(
    db: AsyncSession,
    *,
    order_type: OrderType,
    organization_id: UUID | None = None,
    organization_slug: str | None = None,
) -> Organization:
    statement = select(Organization).options(selectinload(Organization.iiko_menu_snapshot))

    if order_type == "pickup":
        if organization_id is not None:
            statement = statement.where(Organization.id == organization_id)
        elif organization_slug is not None:
            statement = statement.where(Organization.slug == organization_slug.strip().lower())
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "organization_id or organization_slug is required for pickup")

        organization = await db.scalar(statement)
        if not organization:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
        if not organization.accepts_pickup:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Organization does not accept pickup orders")
        if not organization.iiko_organization_id:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Organization iiko id is not configured")
        return organization

    if organization_id is not None or organization_slug is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Delivery menu is selected by the backend")

    organization = await db.scalar(
        statement.where(Organization.accepts_delivery.is_(True))
        .order_by(Organization.is_default_delivery.desc(), Organization.name)
        .limit(1)
    )
    if not organization:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Delivery organization is not configured")
    if not organization.iiko_organization_id:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Delivery organization iiko id is not configured")

    return organization


async def list_menu_item_contents(db: AsyncSession, *, active_only: bool = False) -> list[MenuItemContent]:
    statement = select(MenuItemContent).order_by(MenuItemContent.sort_order, MenuItemContent.created_at)
    if active_only:
        statement = statement.where(MenuItemContent.is_active.is_(True))

    return list(await db.scalars(statement))


async def get_menu_item_content_by_id(db: AsyncSession, content_id: UUID) -> MenuItemContent:
    content = await db.scalar(select(MenuItemContent).where(MenuItemContent.id == content_id))
    if not content:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Menu item content not found")

    return content


async def create_menu_item_content(db: AsyncSession, payload: MenuItemContentCreate) -> MenuItemContent:
    content = MenuItemContent(
        iiko_item_id=payload.iiko_item_id,
        sku=payload.sku,
        name_override=payload.name_override,
        description=payload.description,
        image_url=str(payload.image_url) if payload.image_url is not None else None,
        sort_order=payload.sort_order,
        is_active=payload.is_active,
    )
    db.add(content)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Menu item content already exists for this iiko item or sku")

    return await get_menu_item_content_by_id(db, content.id)


async def update_menu_item_content(
    db: AsyncSession,
    content_id: UUID,
    payload: MenuItemContentUpdate,
) -> MenuItemContent:
    content = await get_menu_item_content_by_id(db, content_id)
    data = payload.model_dump(exclude_unset=True)
    old_image_url: str | None = None

    for field in ("iiko_item_id", "sku", "name_override", "description", "sort_order", "is_active"):
        if field in data:
            setattr(content, field, data[field])

    if not content.iiko_item_id and not content.sku:
        await db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "iiko_item_id or sku is required")

    if "image_url" in data:
        next_image_url = str(payload.image_url) if payload.image_url is not None else None
        if content.image_url != next_image_url:
            old_image_url = content.image_url
        content.image_url = next_image_url

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Menu item content already exists for this iiko item or sku")

    delete_local_media_file(old_image_url)
    return await get_menu_item_content_by_id(db, content.id)


async def upload_menu_item_image(db: AsyncSession, content_id: UUID, image: UploadFile) -> MenuItemContent:
    content = await get_menu_item_content_by_id(db, content_id)
    old_image_url = content.image_url
    content.image_url = await save_media_upload(image, "menu", str(content.id))
    await db.commit()

    delete_local_media_file(old_image_url)
    return await get_menu_item_content_by_id(db, content.id)


async def delete_menu_item_content(db: AsyncSession, content_id: UUID) -> None:
    content = await get_menu_item_content_by_id(db, content_id)
    image_url = content.image_url

    await db.delete(content)
    await db.commit()
    delete_local_media_file(image_url)


def build_menu_response(
    organization: Organization,
    snapshot: IikoMenuSnapshot,
    contents: list[MenuItemContent],
    *,
    order_type: OrderType,
    is_stale: bool,
) -> dict:
    if not organization.iiko_organization_id:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Organization iiko id is not configured")

    raw_menu = snapshot.raw_menu or {}
    iiko_item_content = {content.iiko_item_id: content for content in contents if content.iiko_item_id}
    sku_content = {content.sku: content for content in contents if content.sku}
    categories = []
    menu = []
    seen_items: set[str] = set()

    for category in raw_menu.get("itemCategories") or []:
        if not isinstance(category, dict) or category.get("isHidden") or category.get("isDeleted"):
            continue

        items = []
        for item in category.get("items") or []:
            if not isinstance(item, dict):
                continue

            normalized_item = normalize_iiko_item(
                item,
                organization.iiko_organization_id,
                iiko_item_content=iiko_item_content,
                sku_content=sku_content,
            )
            if normalized_item is None:
                continue

            dedupe_key = normalized_item["id"] or normalized_item.get("sku")
            if dedupe_key in seen_items:
                continue
            seen_items.add(dedupe_key)
            items.append(normalized_item)

        if not items:
            continue

        category_id = str(category.get("id") or category.get("iikoGroupId") or category.get("name"))
        title = str(category.get("name") or "")
        categories.append({"id": category_id, "title": title})
        menu.append({"id": category_id, "title": title, "items": items})

    return {
        "order_type": order_type,
        "organization_id": organization.id,
        "organization_slug": organization.slug,
        "iiko_organization_id": organization.iiko_organization_id,
        "external_menu_id": snapshot.external_menu_id,
        "external_menu_name": snapshot.external_menu_name,
        "revision": snapshot.revision,
        "synced_at": snapshot.synced_at,
        "is_stale": is_stale,
        "categories": categories,
        "menu": menu,
    }


def normalize_iiko_item(
    item: dict,
    iiko_organization_id: str,
    *,
    iiko_item_content: dict[str, MenuItemContent],
    sku_content: dict[str, MenuItemContent],
) -> dict | None:
    if item.get("isHidden") or item.get("isDeleted"):
        return None

    item_id = str(item.get("itemId") or item.get("id") or "")
    sku = to_optional_str(item.get("sku"))
    item_size = select_item_size(item, iiko_organization_id)
    if item_size is None:
        return None

    price = select_price(item_size, iiko_organization_id)
    if price is None:
        return None

    content = iiko_item_content.get(item_id) if item_id else None
    if content is None and sku:
        content = sku_content.get(sku)

    nutrition = select_nutrition(item_size, iiko_organization_id)
    weight = format_weight(item_size.get("portionWeightGrams"))

    return {
        "id": item_id or sku or str(item.get("name") or ""),
        "sku": sku,
        "name": content.name_override if content and content.name_override else str(item.get("name") or ""),
        "description": content.description if content and content.description is not None else str(item.get("description") or ""),
        "price": price,
        "image": content.image_url if content and content.image_url else to_optional_str(item_size.get("buttonImageUrl") or item.get("buttonImageUrl")),
        "weight": weight,
        "calories": parse_float(nutrition.get("energy")),
        "fats": parse_float(nutrition.get("fats")),
        "proteins": parse_float(nutrition.get("proteins")),
        "carbs": parse_float(nutrition.get("carbs")),
        "size_id": to_optional_str(item_size.get("sizeId")),
        "size_name": to_optional_str(item_size.get("sizeName")),
        "measure_unit_type": to_optional_str(item_size.get("measureUnitType")),
        "modifiers": [group for group in item_size.get("itemModifierGroups") or [] if isinstance(group, dict)],
    }


def select_item_size(item: dict, iiko_organization_id: str) -> dict | None:
    sizes = [size for size in item.get("itemSizes") or [] if isinstance(size, dict) and not size.get("isHidden")]
    if not sizes:
        return None

    default_sizes = [size for size in sizes if size.get("isDefault")]
    for size in [*default_sizes, *sizes]:
        if select_price(size, iiko_organization_id) is not None:
            return size

    return None


def select_price(item_size: dict, iiko_organization_id: str) -> float | None:
    prices = [price for price in item_size.get("prices") or [] if isinstance(price, dict)]
    for price in prices:
        if str(price.get("organizationId")) == iiko_organization_id:
            return parse_float(price.get("price"))

    if len(prices) == 1:
        return parse_float(prices[0].get("price"))

    return None


def select_nutrition(item_size: dict, iiko_organization_id: str) -> dict:
    nutritions = [nutrition for nutrition in item_size.get("nutritions") or [] if isinstance(nutrition, dict)]
    for nutrition in nutritions:
        organizations = [str(item) for item in nutrition.get("organizations") or []]
        if iiko_organization_id in organizations:
            return nutrition

    nutrition_per_hundred = item_size.get("nutritionPerHundredGrams")
    return nutrition_per_hundred if isinstance(nutrition_per_hundred, dict) else {}


def format_weight(value) -> str | None:
    weight = parse_float(value)
    if weight is None or weight <= 0:
        return None

    if weight.is_integer():
        return f"{int(weight)} g"

    return f"{weight:g} g"


def parse_float(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_int(value) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def to_optional_str(value) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


async def refresh_iiko_menus_once() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.scalars(
            select(Organization)
            .options(selectinload(Organization.iiko_menu_snapshot))
            .where(
                Organization.iiko_api_login.is_not(None),
                Organization.iiko_organization_id.is_not(None),
            )
            .order_by(Organization.name)
        )
        organizations = list(result.unique())

        for organization in organizations:
            try:
                await sync_iiko_menu_for_organization(db, organization)
            except IikoMenuError as exc:
                logger.warning("iiko menu sync failed for organization %s: %s", organization.id, exc)


async def run_iiko_menu_refresher(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await refresh_iiko_menus_once()
        except Exception:
            logger.exception("Unexpected error while refreshing iiko menus")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.iiko_menu_poll_seconds)
        except asyncio.TimeoutError:
            pass
