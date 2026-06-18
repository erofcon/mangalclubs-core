from pydantic import BaseModel, Field


class MobilePlatformVersionOut(BaseModel):
    min_supported_build: int = Field(serialization_alias="minSupportedBuild")
    latest_build: int = Field(serialization_alias="latestBuild")
    store_url: str | None = Field(default=None, serialization_alias="storeUrl")


class MobileUpdateCopyOut(BaseModel):
    title: str
    message: str


class MobileVersionConfigOut(BaseModel):
    android: MobilePlatformVersionOut
    ios: MobilePlatformVersionOut
    force_update: MobileUpdateCopyOut = Field(serialization_alias="forceUpdate")
    soft_update: MobileUpdateCopyOut = Field(serialization_alias="softUpdate")
