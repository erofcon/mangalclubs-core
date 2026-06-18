from datetime import date
from datetime import datetime
from uuid import UUID
from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator


class DeviceIdentity(BaseModel):
    device_id: str = Field(min_length=8, max_length=128)

    @field_validator("device_id", mode="before")
    @classmethod
    def strip_device_id(cls, value: Any) -> Any:
        if value is None:
            return None

        if isinstance(value, str):
            value = value.strip()
            return value or None

        return value


class DeviceInfo(DeviceIdentity):
    device_name: str | None = Field(default=None, max_length=255)

    @field_validator("device_name", mode="before")
    @classmethod
    def strip_device_name(cls, value: Any) -> Any:
        if value is None:
            return None

        if isinstance(value, str):
            value = value.strip()
            return value or None

        return value


class CustomerOtpRequest(BaseModel):
    phone: str
    device_id: str | None = Field(default=None, min_length=8, max_length=128)
    device_name: str | None = Field(default=None, max_length=255)


class CustomerOtpVerify(DeviceInfo):
    phone: str
    code: str = Field(min_length=4, max_length=8)


class StaffLogin(DeviceInfo):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class RefreshRequest(DeviceInfo):
    refresh_token: str | None = None


class LogoutRequest(DeviceIdentity):
    refresh_token: str | None = None


class AuthSubjectOut(BaseModel):
    id: UUID
    subject_type: str
    phone: str | None = None
    name: str | None = None
    email: str | None = None
    birthday: date | None = None
    avatar_url: str | None = Field(default=None, serialization_alias="avatarUrl")
    role: str | None = None


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: AuthSubjectOut


class OtpRequested(BaseModel):
    ok: bool = True
    message: str = "If the phone is valid, code will be sent"
    retry_after_seconds: int = 0
    resend_available_at: datetime | None = None


class LogoutResponse(BaseModel):
    ok: bool = True
