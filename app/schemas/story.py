from typing import Any
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.models.story import StorySlideMediaType


class StorySlideBase(BaseModel):
    url: HttpUrl | str = Field(
        max_length=1024,
        validation_alias=AliasChoices("url", "src"),
        serialization_alias="src",
    )
    media_type: StorySlideMediaType = Field(
        default=StorySlideMediaType.image,
        validation_alias=AliasChoices("media_type", "type"),
        serialization_alias="type",
    )
    title: str | None = Field(default=None, max_length=255)
    caption: str | None = None
    duration_seconds: int | None = Field(default=None, gt=0)
    sort_order: int = 0
    is_active: bool = True

    @field_validator("url", "title", "caption", mode="before")
    @classmethod
    def strip_optional_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class StorySlideCreate(StorySlideBase):
    pass


class StorySlideUpdate(BaseModel):
    url: HttpUrl | str | None = Field(
        default=None,
        max_length=1024,
        validation_alias=AliasChoices("url", "src"),
        serialization_alias="src",
    )
    media_type: StorySlideMediaType | None = Field(
        default=None,
        validation_alias=AliasChoices("media_type", "type"),
        serialization_alias="type",
    )
    title: str | None = Field(default=None, max_length=255)
    caption: str | None = None
    duration_seconds: int | None = Field(default=None, gt=0)
    sort_order: int | None = None
    is_active: bool | None = None

    @field_validator("url", "title", "caption", mode="before")
    @classmethod
    def strip_optional_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class StorySlideOut(BaseModel):
    id: UUID
    story_id: UUID
    url: str = Field(validation_alias=AliasChoices("url", "src"), serialization_alias="src")
    media_type: StorySlideMediaType = Field(serialization_alias="type")
    title: str | None
    caption: str | None
    duration_seconds: int | None
    sort_order: int
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class StoryCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    title: str = Field(min_length=1, max_length=255)
    preview_url: HttpUrl | str | None = Field(
        default=None,
        max_length=1024,
        validation_alias=AliasChoices("preview_url", "previewImage"),
        serialization_alias="previewImage",
    )
    description: str | None = None
    slides: list[StorySlideCreate] = Field(default_factory=list, max_length=50)
    sort_order: int = 0
    is_active: bool = True

    @field_validator("slug", mode="before")
    @classmethod
    def normalize_slug(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip().lower()
        return value

    @field_validator("title", "preview_url", "description", mode="before")
    @classmethod
    def strip_story_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class StoryUpdate(BaseModel):
    slug: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    title: str | None = Field(default=None, min_length=1, max_length=255)
    preview_url: HttpUrl | str | None = Field(
        default=None,
        max_length=1024,
        validation_alias=AliasChoices("preview_url", "previewImage"),
        serialization_alias="previewImage",
    )
    description: str | None = None
    slides: list[StorySlideCreate] | None = Field(default=None, max_length=50)
    sort_order: int | None = None
    is_active: bool | None = None

    @field_validator("slug", mode="before")
    @classmethod
    def normalize_slug(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip().lower()
        return value

    @field_validator("title", "preview_url", "description", mode="before")
    @classmethod
    def strip_optional_story_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class StoryOut(BaseModel):
    id: UUID
    slug: str
    title: str
    preview_url: str | None = Field(
        validation_alias=AliasChoices("preview_url", "previewImage"),
        serialization_alias="previewImage",
    )
    description: str | None
    slides: list[StorySlideOut]
    sort_order: int
    is_active: bool

    model_config = ConfigDict(from_attributes=True)
