from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

class BookingOrganizationOut(BaseModel):
    id: UUID
    slug: str
    name: str
    phone: str

    model_config = ConfigDict(from_attributes=True)


class BookingImageBase(BaseModel):
    url: HttpUrl | str = Field(max_length=1024)
    alt_text: str | None = Field(default=None, max_length=255)
    sort_order: int = 0

    @field_validator("url", "alt_text", mode="before")
    @classmethod
    def strip_optional_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
        return value


class BookingImageCreate(BookingImageBase):
    pass


class BookingImageUpdate(BookingImageBase):
    pass


class BookingImageOut(BookingImageBase):
    id: UUID
    url: str

    model_config = ConfigDict(from_attributes=True)


class BookingCategoryCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    preview_url: HttpUrl | str | None = Field(default=None, max_length=1024)
    sort_order: int = 0
    is_active: bool = True

    @field_validator("title", "description", "preview_url", mode="before")
    @classmethod
    def strip_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class BookingCategoryUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    preview_url: HttpUrl | str | None = Field(default=None, max_length=1024)
    sort_order: int | None = None
    is_active: bool | None = None

    @field_validator("title", "description", "preview_url", mode="before")
    @classmethod
    def strip_optional_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class BookingCategoryOut(BaseModel):
    id: UUID
    title: str
    description: str | None
    preview_url: str | None
    sort_order: int
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class BookingCreate(BaseModel):
    organization_id: UUID
    category_id: UUID
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    long_description: str | None = None
    preview_url: HttpUrl | str | None = Field(default=None, max_length=1024)
    images: list[BookingImageCreate] = Field(default_factory=list, max_length=24)
    sort_order: int = 0
    is_active: bool = True

    @field_validator("title", "description", "long_description", "preview_url", mode="before")
    @classmethod
    def strip_booking_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @model_validator(mode="after")
    def validate_images_limit(self) -> "BookingCreate":
        if len(self.images) > 24:
            raise ValueError("A booking can have at most 24 images")
        return self


class BookingUpdate(BaseModel):
    organization_id: UUID | None = None
    category_id: UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1)
    long_description: str | None = None
    preview_url: HttpUrl | str | None = Field(default=None, max_length=1024)
    images: list[BookingImageUpdate] | None = Field(default=None, max_length=24)
    sort_order: int | None = None
    is_active: bool | None = None

    @field_validator("title", "description", "long_description", "preview_url", mode="before")
    @classmethod
    def strip_optional_booking_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @model_validator(mode="after")
    def validate_images_limit(self) -> "BookingUpdate":
        if self.images is not None and len(self.images) > 24:
            raise ValueError("A booking can have at most 24 images")
        return self


class BookingOut(BaseModel):
    id: UUID
    organization_id: UUID
    category_id: UUID
    title: str
    description: str
    long_description: str | None
    preview_url: str | None
    images: list[BookingImageOut]
    sort_order: int
    is_active: bool
    organization: BookingOrganizationOut
    category: BookingCategoryOut

    model_config = ConfigDict(from_attributes=True)
