from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.datastructures import UploadFile

from app.models.story import Story, StorySlide, StorySlideMediaType
from app.schemas.story import StoryCreate, StorySlideCreate, StorySlideUpdate, StoryUpdate
from app.services.media import delete_local_media_file, save_media_upload


def story_query(*, include_inactive_slides: bool = False):
    loader = selectinload(Story.slides)
    if not include_inactive_slides:
        loader = selectinload(Story.slides.and_(StorySlide.is_active.is_(True)))
    return select(Story).options(loader)


async def list_stories(db: AsyncSession, *, include_inactive: bool = False) -> list[Story]:
    statement = story_query(include_inactive_slides=include_inactive)
    if not include_inactive:
        statement = statement.where(Story.is_active.is_(True))

    result = await db.scalars(statement.order_by(Story.sort_order, Story.title))
    return list(result.unique())


async def get_story_by_id(db: AsyncSession, story_id: UUID, *, include_inactive: bool = False) -> Story:
    statement = story_query(include_inactive_slides=include_inactive).where(Story.id == story_id)
    if not include_inactive:
        statement = statement.where(Story.is_active.is_(True))

    story = await db.scalar(statement)
    if not story:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Story not found")

    return story


async def get_story_by_slug(db: AsyncSession, slug: str, *, include_inactive: bool = False) -> Story:
    statement = story_query(include_inactive_slides=include_inactive).where(Story.slug == slug.strip().lower())
    if not include_inactive:
        statement = statement.where(Story.is_active.is_(True))

    story = await db.scalar(statement)
    if not story:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Story not found")

    return story


async def create_story(db: AsyncSession, payload: StoryCreate) -> Story:
    story = Story(
        slug=payload.slug,
        title=payload.title,
        preview_url=str(payload.preview_url) if payload.preview_url is not None else None,
        description=payload.description,
        sort_order=payload.sort_order,
        is_active=payload.is_active,
    )
    replace_story_slides(story, payload.slides)
    db.add(story)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Story already exists or slide sort order is duplicated")

    return await get_story_by_id(db, story.id, include_inactive=True)


async def update_story(db: AsyncSession, story_id: UUID, payload: StoryUpdate) -> Story:
    story = await get_story_by_id(db, story_id, include_inactive=True)
    data = payload.model_dump(exclude_unset=True)
    old_media_urls: list[str | None] = []

    for field in ("slug", "title", "description", "sort_order", "is_active"):
        if field in data:
            setattr(story, field, data[field])

    if "preview_url" in data:
        next_preview_url = str(payload.preview_url) if payload.preview_url is not None else None
        if story.preview_url != next_preview_url:
            old_media_urls.append(story.preview_url)
        story.preview_url = next_preview_url

    if payload.slides is not None:
        next_urls = {str(slide.url) for slide in payload.slides if slide.url is not None}
        old_media_urls.extend(slide.url for slide in story.slides if slide.url not in next_urls)
        replace_story_slides(story, payload.slides)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Story already exists or slide sort order is duplicated")

    for media_url in old_media_urls:
        delete_local_media_file(media_url)

    return await get_story_by_id(db, story.id, include_inactive=True)


async def delete_story(db: AsyncSession, story_id: UUID) -> None:
    story = await get_story_by_id(db, story_id, include_inactive=True)
    media_urls = [story.preview_url, *(slide.url for slide in story.slides)]

    await db.delete(story)
    await db.commit()

    for media_url in media_urls:
        delete_local_media_file(media_url)


async def upload_story_preview(db: AsyncSession, story_id: UUID, file: UploadFile) -> Story:
    story = await get_story_by_id(db, story_id, include_inactive=True)
    old_preview_url = story.preview_url
    story.preview_url = await save_media_upload(file, "stories", str(story.id))
    await db.commit()

    delete_local_media_file(old_preview_url)
    return await get_story_by_id(db, story.id, include_inactive=True)


async def add_story_slide(
    db: AsyncSession,
    story_id: UUID,
    file: UploadFile,
    *,
    title: str | None = None,
    caption: str | None = None,
    duration_seconds: int | None = None,
    sort_order: int = 0,
    is_active: bool = True,
) -> Story:
    story = await get_story_by_id(db, story_id, include_inactive=True)
    media_type = get_media_type(file)
    slide = StorySlide(
        story_id=story.id,
        url=await save_media_upload(file, "stories", str(story.id), allow_video=True),
        media_type=media_type,
        title=title.strip() if title else None,
        caption=caption.strip() if caption else None,
        duration_seconds=duration_seconds,
        sort_order=sort_order,
        is_active=is_active,
    )
    db.add(slide)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        delete_local_media_file(slide.url)
        raise HTTPException(status.HTTP_409_CONFLICT, "Slide sort order is duplicated")

    return await get_story_by_id(db, story.id, include_inactive=True)


async def update_story_slide(
    db: AsyncSession,
    story_id: UUID,
    slide_id: UUID,
    payload: StorySlideUpdate,
) -> Story:
    story = await get_story_by_id(db, story_id, include_inactive=True)
    slide = get_story_slide(story, slide_id)
    data = payload.model_dump(exclude_unset=True)
    old_media_url: str | None = None

    for field in ("media_type", "title", "caption", "duration_seconds", "sort_order", "is_active"):
        if field in data:
            setattr(slide, field, data[field])

    if "url" in data and payload.url is not None:
        next_url = str(payload.url)
        if slide.url != next_url:
            old_media_url = slide.url
        slide.url = next_url

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Slide sort order is duplicated")

    delete_local_media_file(old_media_url)
    return await get_story_by_id(db, story.id, include_inactive=True)


async def upload_story_slide_media(
    db: AsyncSession,
    story_id: UUID,
    slide_id: UUID,
    file: UploadFile,
) -> Story:
    story = await get_story_by_id(db, story_id, include_inactive=True)
    slide = get_story_slide(story, slide_id)
    old_media_url = slide.url

    slide.media_type = get_media_type(file)
    slide.url = await save_media_upload(file, "stories", str(story.id), allow_video=True)
    await db.commit()

    delete_local_media_file(old_media_url)
    return await get_story_by_id(db, story.id, include_inactive=True)


async def delete_story_slide(db: AsyncSession, story_id: UUID, slide_id: UUID) -> Story:
    story = await get_story_by_id(db, story_id, include_inactive=True)
    slide = get_story_slide(story, slide_id)
    media_url = slide.url

    await db.delete(slide)
    await db.commit()

    delete_local_media_file(media_url)
    return await get_story_by_id(db, story.id, include_inactive=True)


def get_story_slide(story: Story, slide_id: UUID) -> StorySlide:
    slide = next((item for item in story.slides if item.id == slide_id), None)
    if slide is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Story slide not found")

    return slide


def get_media_type(file: UploadFile) -> StorySlideMediaType:
    if (file.content_type or "").startswith("video/"):
        return StorySlideMediaType.video

    return StorySlideMediaType.image


def replace_story_slides(story: Story, slides: list[StorySlideCreate]) -> None:
    story.slides = [
        StorySlide(
            url=str(item.url),
            media_type=item.media_type or StorySlideMediaType.image,
            title=item.title,
            caption=item.caption,
            duration_seconds=item.duration_seconds,
            sort_order=item.sort_order if item.sort_order is not None else 0,
            is_active=item.is_active if item.is_active is not None else True,
        )
        for item in slides
        if item.url is not None
    ]
