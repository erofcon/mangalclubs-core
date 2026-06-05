from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, status
from starlette.datastructures import UploadFile

from app.core.config import settings


ALLOWED_PHOTO_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
ALLOWED_VIDEO_CONTENT_TYPES = {
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
}
MAX_PHOTO_SIZE_BYTES = 8 * 1024 * 1024
MAX_VIDEO_SIZE_BYTES = 80 * 1024 * 1024


def validate_photo_upload(file: UploadFile) -> str:
    extension = ALLOWED_PHOTO_CONTENT_TYPES.get(file.content_type or "")
    if not extension:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only JPEG, PNG, and WebP photos are supported")

    return extension


def validate_story_media_upload(file: UploadFile) -> tuple[str, str, int]:
    content_type = file.content_type or ""
    photo_extension = ALLOWED_PHOTO_CONTENT_TYPES.get(content_type)
    if photo_extension:
        return photo_extension, "Photo is too large", MAX_PHOTO_SIZE_BYTES

    video_extension = ALLOWED_VIDEO_CONTENT_TYPES.get(content_type)
    if video_extension:
        return video_extension, "Video is too large", MAX_VIDEO_SIZE_BYTES

    raise HTTPException(
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        "Only JPEG, PNG, WebP, MP4, WebM, and MOV story media are supported",
    )


async def save_media_upload(
    file: UploadFile,
    folder: str,
    filename_prefix: str,
    *,
    allow_video: bool = False,
) -> str:
    if allow_video:
        extension, size_error_message, max_size_bytes = validate_story_media_upload(file)
    else:
        extension = validate_photo_upload(file)
        size_error_message = "Photo is too large"
        max_size_bytes = MAX_PHOTO_SIZE_BYTES

    media_dir = Path(settings.media_root) / folder
    media_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{filename_prefix}-{uuid4().hex}{extension}"
    destination = media_dir / filename

    written = 0
    try:
        with destination.open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > max_size_bytes:
                    raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, size_error_message)
                target.write(chunk)
    except Exception:
        if destination.exists():
            destination.unlink()
        raise
    finally:
        await file.close()

    return f"{settings.media_url.rstrip('/')}/{folder}/{filename}"


def delete_local_media_file(photo_url: str | None) -> None:
    media_url = settings.media_url.rstrip("/")
    if not photo_url or not photo_url.startswith(f"{media_url}/"):
        return

    media_root = Path(settings.media_root).resolve()
    relative_url = photo_url.removeprefix(f"{media_url}/")
    target = (media_root / relative_url).resolve()

    if media_root not in target.parents or not target.is_file():
        return

    target.unlink()
