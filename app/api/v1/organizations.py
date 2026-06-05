from uuid import UUID

from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.db.session import get_db
from app.models.staff import StaffUser
from app.schemas.organization import OrganizationCreate, OrganizationOut, OrganizationUpdate
from app.services.organizations import (
    create_organization,
    delete_organization,
    get_organization_by_slug,
    list_organizations,
    update_organization,
    upload_organization_photo,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("", response_model=list[OrganizationOut])
async def organizations_list(db: AsyncSession = Depends(get_db)):
    return await list_organizations(db)


@router.get("/{slug}", response_model=OrganizationOut)
async def organizations_get(slug: str, db: AsyncSession = Depends(get_db)):
    return await get_organization_by_slug(db, slug)


@router.post("", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
async def organizations_create(
    payload: OrganizationCreate,
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await create_organization(db, payload)


@router.patch("/{organization_id}", response_model=OrganizationOut)
async def organizations_update(
    organization_id: UUID,
    payload: OrganizationUpdate,
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await update_organization(db, organization_id, payload)


@router.post("/{organization_id}/photo", response_model=OrganizationOut)
async def organizations_upload_photo(
    organization_id: UUID,
    photo: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await upload_organization_photo(db, organization_id, photo)


@router.delete("/{organization_id}", status_code=status.HTTP_204_NO_CONTENT)
async def organizations_delete(
    organization_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    await delete_organization(db, organization_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
