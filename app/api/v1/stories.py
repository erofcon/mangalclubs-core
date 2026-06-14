from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.db.session import get_db
from app.models.staff import StaffUser
from app.schemas.story import StoryCreate, StoryOut, StoryPublicOut, StorySlideUpdate, StoryUpdate
from app.services.stories import (
    add_story_slide,
    create_story,
    delete_story,
    delete_story_slide,
    get_story_by_id,
    get_story_by_slug,
    list_stories,
    update_story,
    update_story_slide,
    upload_story_preview,
    upload_story_slide_media,
)

router = APIRouter(prefix="/stories", tags=["stories"])


@router.get("", response_model=list[StoryPublicOut])
async def stories_list(db: AsyncSession = Depends(get_db)):
    return await list_stories(db)


@router.get("/admin/all", response_model=list[StoryOut])
async def stories_admin_list(
    include_inactive: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await list_stories(db, include_inactive=include_inactive)


@router.get("/admin/{story_id}", response_model=StoryOut)
async def stories_admin_get(
    story_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await get_story_by_id(db, story_id, include_inactive=True)


@router.get("/{slug}", response_model=StoryPublicOut)
async def stories_get(slug: str, db: AsyncSession = Depends(get_db)):
    return await get_story_by_slug(db, slug)


@router.post("", response_model=StoryOut, status_code=status.HTTP_201_CREATED)
async def stories_create(
    payload: StoryCreate,
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await create_story(db, payload)


@router.patch("/{story_id}", response_model=StoryOut)
async def stories_update(
    story_id: UUID,
    payload: StoryUpdate,
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await update_story(db, story_id, payload)


@router.post("/{story_id}/preview", response_model=StoryOut)
async def stories_upload_preview(
    story_id: UUID,
    preview: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await upload_story_preview(db, story_id, preview)


@router.post("/{story_id}/slides", response_model=StoryOut)
async def stories_add_slide(
    story_id: UUID,
    media: UploadFile = File(...),
    title: str | None = Form(default=None),
    caption: str | None = Form(default=None),
    duration_seconds: int | None = Form(default=None),
    sort_order: int = Form(default=0),
    is_active: bool = Form(default=True),
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await add_story_slide(
        db,
        story_id,
        media,
        title=title,
        caption=caption,
        duration_seconds=duration_seconds,
        sort_order=sort_order,
        is_active=is_active,
    )


@router.patch("/{story_id}/slides/{slide_id}", response_model=StoryOut)
async def stories_update_slide(
    story_id: UUID,
    slide_id: UUID,
    payload: StorySlideUpdate,
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await update_story_slide(db, story_id, slide_id, payload)


@router.post("/{story_id}/slides/{slide_id}/media", response_model=StoryOut)
async def stories_upload_slide_media(
    story_id: UUID,
    slide_id: UUID,
    media: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await upload_story_slide_media(db, story_id, slide_id, media)


@router.delete("/{story_id}/slides/{slide_id}", response_model=StoryOut)
async def stories_delete_slide(
    story_id: UUID,
    slide_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    return await delete_story_slide(db, story_id, slide_id)


@router.delete("/{story_id}", status_code=status.HTTP_204_NO_CONTENT)
async def stories_delete(
    story_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: StaffUser = Depends(get_current_admin),
):
    await delete_story(db, story_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
