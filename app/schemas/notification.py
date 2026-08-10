from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.core.time import to_moscow


OrderNotificationEvent = Literal["order_created", "pickup_ready", "delivery_on_way", "delivery_delivered"]


class CustomerDeviceRegisterIn(BaseModel):
    device_id: str = Field(validation_alias="deviceId", min_length=1, max_length=128)
    push_token: str = Field(validation_alias="pushToken", min_length=1, max_length=255)
    platform: str | None = Field(default=None, max_length=32)
    device_name: str | None = Field(default=None, validation_alias="deviceName", max_length=255)

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("device_id", "push_token", "platform", "device_name", mode="before")
    @classmethod
    def strip_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class CustomerDeviceOut(BaseModel):
    id: UUID
    device_id: str = Field(serialization_alias="deviceId")
    push_token: str = Field(serialization_alias="pushToken")
    platform: str | None
    device_name: str | None = Field(default=None, serialization_alias="deviceName")
    is_active: bool = Field(serialization_alias="isActive")
    updated_at: datetime = Field(serialization_alias="updatedAt")

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("updated_at")
    def serialize_moscow_datetime(self, value: datetime) -> datetime:
        return to_moscow(value)


class CustomerOrderNotificationOut(BaseModel):
    id: UUID
    order_id: UUID = Field(serialization_alias="orderId")
    event_type: OrderNotificationEvent | str = Field(serialization_alias="eventType")
    title: str
    body: str
    is_read: bool = Field(serialization_alias="isRead")
    created_at: datetime = Field(serialization_alias="createdAt")

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("created_at")
    def serialize_moscow_datetime(self, value: datetime) -> datetime:
        return to_moscow(value)


class CustomerUnreadNotificationsOut(BaseModel):
    count: int
    order_ids: list[UUID] = Field(serialization_alias="orderIds")
    notifications: list[CustomerOrderNotificationOut]
