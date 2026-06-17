from pathlib import Path
from io import BytesIO
from uuid import uuid4

from fastapi import HTTPException, status
from PIL import Image, ImageOps, UnidentifiedImageError
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
MAX_AVATAR_SOURCE_SIZE_BYTES = 8 * 1024 * 1024
AVATAR_SIZE_PX = 512
AVATAR_JPEG_QUALITY = 85


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


def prepare_avatar_image(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image)
    crop_size = min(image.size)
    left = (image.width - crop_size) // 2
    top = (image.height - crop_size) // 2
    image = image.crop((left, top, left + crop_size, top + crop_size))
    image = image.resize((AVATAR_SIZE_PX, AVATAR_SIZE_PX), Image.Resampling.LANCZOS)

    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        transparent = image.convert("RGBA")
        background = Image.new("RGB", transparent.size, (255, 255, 255))
        background.paste(transparent, mask=transparent.getchannel("A"))
        return background

    return image.convert("RGB")


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


async def save_avatar_upload(
    file: UploadFile,
    folder: str,
    filename_prefix: str,
) -> str:
    validate_photo_upload(file)

    content = bytearray()
    try:
        while chunk := await file.read(1024 * 1024):
            content.extend(chunk)
            if len(content) > MAX_AVATAR_SOURCE_SIZE_BYTES:
                raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Avatar image is too large")
    finally:
        await file.close()

    try:
        with Image.open(BytesIO(content)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"}:
                raise HTTPException(
                    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    "Only JPEG, PNG, and WebP avatars are supported",
                )

            optimized = prepare_avatar_image(image)
    except UnidentifiedImageError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Avatar file is not a valid image") from exc

    media_dir = Path(settings.media_root) / folder
    media_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{filename_prefix}-{uuid4().hex}.jpg"
    destination = media_dir / filename

    try:
        optimized.save(
            destination,
            format="JPEG",
            quality=AVATAR_JPEG_QUALITY,
            optimize=True,
            progressive=True,
        )
    except Exception:
        if destination.exists():
            destination.unlink()
        raise

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
