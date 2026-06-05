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
MAX_PHOTO_SIZE_BYTES = 8 * 1024 * 1024


def validate_photo_upload(file: UploadFile) -> str:
    extension = ALLOWED_PHOTO_CONTENT_TYPES.get(file.content_type or "")
    if not extension:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only JPEG, PNG, and WebP photos are supported")

    return extension


async def save_media_upload(file: UploadFile, folder: str, filename_prefix: str) -> str:
    extension = validate_photo_upload(file)
    photo_dir = Path(settings.media_root) / folder
    photo_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{filename_prefix}-{uuid4().hex}{extension}"
    destination = photo_dir / filename

    written = 0
    try:
        with destination.open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_PHOTO_SIZE_BYTES:
                    raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Photo is too large")
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
