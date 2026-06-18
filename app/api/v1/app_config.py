from fastapi import APIRouter

from app.core.config import settings
from app.schemas.app_config import (
    MobilePlatformVersionOut,
    MobileUpdateCopyOut,
    MobileVersionConfigOut,
)

router = APIRouter(prefix="/app", tags=["app"])


@router.get("/mobile-version", response_model=MobileVersionConfigOut)
async def mobile_version_config():
    return MobileVersionConfigOut(
        android=MobilePlatformVersionOut(
            min_supported_build=settings.mobile_android_min_supported_build,
            latest_build=max(
                settings.mobile_android_latest_build,
                settings.mobile_android_min_supported_build,
            ),
            store_url=settings.mobile_android_store_url,
        ),
        ios=MobilePlatformVersionOut(
            min_supported_build=settings.mobile_ios_min_supported_build,
            latest_build=max(
                settings.mobile_ios_latest_build,
                settings.mobile_ios_min_supported_build,
            ),
            store_url=settings.mobile_ios_store_url,
        ),
        force_update=MobileUpdateCopyOut(
            title=settings.mobile_force_update_title,
            message=settings.mobile_force_update_message,
        ),
        soft_update=MobileUpdateCopyOut(
            title=settings.mobile_soft_update_title,
            message=settings.mobile_soft_update_message,
        ),
    )
