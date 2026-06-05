from datetime import time
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


class CoordinatesIn(BaseModel):
    latitude: Decimal = Field(ge=-90, le=90, max_digits=9, decimal_places=6)
    longitude: Decimal = Field(ge=-180, le=180, max_digits=9, decimal_places=6)


class CoordinatesOut(BaseModel):
    latitude: float
    longitude: float


class OrganizationWorkingHourBase(BaseModel):
    weekday: int = Field(ge=0, le=6, description="0 is Monday, 6 is Sunday.")
    is_closed: bool = False
    opens_at: time | None = None
    closes_at: time | None = None

    @model_validator(mode="after")
    def validate_time_presence(self):
        if self.is_closed:
            if self.opens_at is not None or self.closes_at is not None:
                raise ValueError("Closed day must not include opens_at or closes_at")
            return self

        if self.opens_at is None or self.closes_at is None:
            raise ValueError("Working day must include opens_at and closes_at")

        return self


class OrganizationWorkingHourCreate(OrganizationWorkingHourBase):
    pass


class OrganizationWorkingHourUpdate(OrganizationWorkingHourBase):
    pass


class OrganizationWorkingHourOut(OrganizationWorkingHourBase):
    closes_next_day: bool

    model_config = ConfigDict(from_attributes=True)


class OrganizationBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    city: str = Field(min_length=1, max_length=255)
    address: str = Field(min_length=1, max_length=500)
    phone: str = Field(min_length=1, max_length=32)
    intro: str = Field(min_length=1)
    coordinates: CoordinatesIn
    photo_url: HttpUrl | str | None = Field(default=None, max_length=1024)
    working_hours: list[OrganizationWorkingHourCreate] = Field(min_length=1, max_length=7)

    @field_validator("name", "city", "address", "phone", "intro", mode="before")
    @classmethod
    def strip_required_strings(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
        return value

    @field_validator("photo_url", mode="before")
    @classmethod
    def strip_optional_photo_url(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("working_hours")
    @classmethod
    def validate_unique_weekdays(cls, value: list[OrganizationWorkingHourCreate]) -> list[OrganizationWorkingHourCreate]:
        weekdays = [item.weekday for item in value]
        if len(weekdays) != len(set(weekdays)):
            raise ValueError("working_hours must contain each weekday only once")
        return value


class OrganizationCreate(OrganizationBase):
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")

    @field_validator("slug", mode="before")
    @classmethod
    def normalize_slug(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip().lower()
        return value


class OrganizationUpdate(BaseModel):
    slug: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str | None = Field(default=None, min_length=1, max_length=255)
    city: str | None = Field(default=None, min_length=1, max_length=255)
    address: str | None = Field(default=None, min_length=1, max_length=500)
    phone: str | None = Field(default=None, min_length=1, max_length=32)
    intro: str | None = Field(default=None, min_length=1)
    coordinates: CoordinatesIn | None = None
    photo_url: HttpUrl | str | None = Field(default=None, max_length=1024)
    working_hours: list[OrganizationWorkingHourUpdate] | None = Field(default=None, min_length=1, max_length=7)

    @field_validator("slug", mode="before")
    @classmethod
    def normalize_update_slug(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip().lower()
        return value

    @field_validator("name", "city", "address", "phone", "intro", mode="before")
    @classmethod
    def strip_optional_strings(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
        return value

    @field_validator("photo_url", mode="before")
    @classmethod
    def strip_update_photo_url(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("working_hours")
    @classmethod
    def validate_update_unique_weekdays(
        cls,
        value: list[OrganizationWorkingHourUpdate] | None,
    ) -> list[OrganizationWorkingHourUpdate] | None:
        if value is None:
            return None

        weekdays = [item.weekday for item in value]
        if len(weekdays) != len(set(weekdays)):
            raise ValueError("working_hours must contain each weekday only once")
        return value


class OrganizationOut(BaseModel):
    id: UUID
    slug: str
    name: str
    city: str
    address: str
    phone: str
    intro: str
    coordinates: CoordinatesOut
    photo_url: str | None
    working_hours: list[OrganizationWorkingHourOut]

    model_config = ConfigDict(from_attributes=True)
