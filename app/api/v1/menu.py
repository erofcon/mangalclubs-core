from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.db.session import get_db
from app.models.staff import StaffUser
from app.schemas.menu import MenuItemContentCreate, MenuItemContentOut, MenuItemContentUpdate, MenuOut, OrderType
from app.services.menu import (
    create_menu_item_content,
    delete_menu_item_content,
    get_menu,
    get_organization_menu,
    get_menu_item_content_by_id,
    list_menu_item_contents,
    sync_iiko_menu_for_organization,
    update_menu_item_content,
    upload_menu_item_image,
)
from app.services.organizations import get_organization_by_id

router = APIRouter(prefix="/menu", tags=["menu"])


@router.get("", response_model=MenuOut)
async def menu_get(
    order_type: OrderType = Query(alias="orderType"),
    organization_id: UUID | None = Query(default=None, alias="organizationId"),
    organization_slug: str | None = Query(default=None, alias="organizationSlug"),
    db: AsyncSession = Depends(get_db),
):
    return await get_menu(
        db,
        order_type=order_type,
        organization_id=organization_id,
        organization_slug=organization_slug,
    )


@router.post("/admin/organizations/{organization_id}/sync", response_model=MenuOut)
async def menu_admin_sync_organization(
    organization_id: UUID,
    order_type: OrderType = Query(default="pickup", alias="orderType"),
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    organization = await get_organization_by_id(db, organization_id)
    await sync_iiko_menu_for_organization(db, organization)
    return await get_organization_menu(db, organization, order_type=order_type)


@router.get("/admin/organizations/{organization_id}", response_model=MenuOut)
async def menu_admin_get_organization(
    organization_id: UUID,
    order_type: OrderType = Query(default="pickup", alias="orderType"),
    refresh: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    organization = await get_organization_by_id(db, organization_id)
    if refresh:
        await sync_iiko_menu_for_organization(db, organization)
    return await get_organization_menu(db, organization, order_type=order_type)


@router.get("/admin/items", response_model=list[MenuItemContentOut])
async def menu_admin_items_list(
    active_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await list_menu_item_contents(db, active_only=active_only)


@router.get("/admin/items/{content_id}", response_model=MenuItemContentOut)
async def menu_admin_items_get(
    content_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await get_menu_item_content_by_id(db, content_id)


@router.post("/admin/items", response_model=MenuItemContentOut, status_code=status.HTTP_201_CREATED)
async def menu_admin_items_create(
    payload: MenuItemContentCreate,
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await create_menu_item_content(db, payload)


@router.patch("/admin/items/{content_id}", response_model=MenuItemContentOut)
async def menu_admin_items_update(
    content_id: UUID,
    payload: MenuItemContentUpdate,
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await update_menu_item_content(db, content_id, payload)


@router.post("/admin/items/{content_id}/image", response_model=MenuItemContentOut)
async def menu_admin_items_upload_image(
    content_id: UUID,
    image: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await upload_menu_item_image(db, content_id, image)


@router.delete("/admin/items/{content_id}", status_code=status.HTTP_204_NO_CONTENT)
async def menu_admin_items_delete(
    content_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    await delete_menu_item_content(db, content_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
