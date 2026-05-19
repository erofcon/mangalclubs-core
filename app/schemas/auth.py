from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class DeviceInfo(BaseModel):
    device_id: str | None = Field(default=None, max_length=128)
    device_name: str | None = Field(default=None, max_length=255)


class CustomerOtpRequest(DeviceInfo):
    phone: str


class CustomerOtpVerify(DeviceInfo):
    phone: str
    code: str = Field(min_length=4, max_length=8)


class StaffLogin(DeviceInfo):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class RefreshRequest(DeviceInfo):
    refresh_token: str


class LogoutRequest(DeviceInfo):
    refresh_token: str


class AuthSubjectOut(BaseModel):
    id: UUID
    subject_type: str
    phone: str | None = None
    email: str | None = None
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


class LogoutResponse(BaseModel):
    ok: bool = True
