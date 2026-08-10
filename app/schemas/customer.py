from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_serializer, field_validator

from app.core.time import to_moscow


class CustomerOut(BaseModel):
    id: UUID
    phone: str
    name: str | None
    email: EmailStr | None
    birthday: date | None
    avatar_url: str | None = Field(default=None, serialization_alias="avatarUrl")
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("created_at", "updated_at")
    def serialize_moscow_datetime(self, value: datetime) -> datetime:
        return to_moscow(value)


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    email: EmailStr | None = None
    birthday: date | None = None

    @field_validator("name", "email", mode="before")
    @classmethod
    def strip_optional_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr | None) -> EmailStr | None:
        if value is None:
            return None
        return str(value).lower()
