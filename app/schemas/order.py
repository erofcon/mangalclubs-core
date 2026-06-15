from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

OrderKind = Literal["delivery", "pickup"]
DeliveryStatus = Literal[
    "Unconfirmed",
    "WaitCooking",
    "ReadyForCooking",
    "CookingStarted",
    "CookingCompleted",
    "Waiting",
    "OnWay",
    "Delivered",
    "Closed",
    "Cancelled",
]
OrderCreationStatus = Literal["InProgress", "Success", "Error"]
OrderNotificationEvent = Literal["pickup_ready", "delivery_on_way", "delivery_delivered"]
PaymentStatus = Literal[
    "payment_pending",
    "payment_form_created",
    "paid",
    "payment_failed",
    "payment_cancelled",
    "payment_expired",
]


class OrderModifierIn(BaseModel):
    product_id: str = Field(validation_alias=AliasChoices("productId", "product_id"), min_length=1, max_length=64)
    amount: float = Field(gt=0)
    product_group_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("productGroupId", "product_group_id"),
        min_length=1,
        max_length=64,
    )
    price: float | None = Field(default=None, ge=0)

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("product_id", "product_group_id", mode="before")
    @classmethod
    def strip_optional_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class OrderItemIn(BaseModel):
    product_id: str = Field(validation_alias=AliasChoices("productId", "product_id"), min_length=1, max_length=64)
    amount: float = Field(gt=0)
    price: float | None = Field(default=None, ge=0)
    product_size_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("productSizeId", "product_size_id"),
        min_length=1,
        max_length=64,
    )
    comment: str | None = Field(default=None, max_length=500)
    modifiers: list[OrderModifierIn] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("product_id", "product_size_id", "comment", mode="before")
    @classmethod
    def strip_optional_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class DeliveryCoordinatesIn(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class DeliveryAddressIn(BaseModel):
    city: str = Field(min_length=1, max_length=255)
    street: str = Field(min_length=1, max_length=255)
    house: str = Field(min_length=1, max_length=100)
    index: str | None = Field(default=None, max_length=16)
    building: str | None = Field(default=None, max_length=32)
    flat: str | None = Field(default=None, max_length=100)
    entrance: str | None = Field(default=None, max_length=10)
    floor: str | None = Field(default=None, max_length=10)
    doorphone: str | None = Field(default=None, max_length=32)
    region_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("regionId", "region_id"),
        min_length=1,
        max_length=64,
    )

    model_config = ConfigDict(populate_by_name=True)

    @field_validator(
        "city",
        "street",
        "house",
        "index",
        "building",
        "flat",
        "entrance",
        "floor",
        "doorphone",
        "region_id",
        mode="before",
    )
    @classmethod
    def strip_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class DeliveryPointIn(BaseModel):
    address: DeliveryAddressIn
    coordinates: DeliveryCoordinatesIn | None = None
    comment: str | None = Field(default=None, max_length=500)
    external_cartography_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("externalCartographyId", "external_cartography_id"),
        min_length=1,
        max_length=128,
    )

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("comment", "external_cartography_id", mode="before")
    @classmethod
    def strip_optional_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class OrderCreateIn(BaseModel):
    order_type: OrderKind = Field(validation_alias=AliasChoices("orderType", "order_type"))
    organization_id: UUID | None = Field(
        default=None,
        validation_alias=AliasChoices("organizationId", "organization_id"),
    )
    organization_slug: str | None = Field(
        default=None,
        validation_alias=AliasChoices("organizationSlug", "organization_slug"),
        min_length=1,
        max_length=64,
    )
    phone: str | None = Field(default=None, min_length=8, max_length=32)
    comment: str | None = Field(default=None, max_length=1000)
    complete_before: datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("completeBefore", "complete_before"),
    )
    delivery_point: DeliveryPointIn | None = Field(
        default=None,
        validation_alias=AliasChoices("deliveryPoint", "delivery_point"),
    )
    guests_count: int = Field(default=1, validation_alias=AliasChoices("guestsCount", "guests_count"), ge=1, le=100)
    items: list[OrderItemIn] = Field(min_length=1, max_length=100)
    success_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SuccessURL", "successUrl", "success_url"),
        max_length=2048,
    )
    fail_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("FailURL", "failUrl", "fail_url"),
        max_length=2048,
    )

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("phone", "comment", "organization_slug", "success_url", "fail_url", mode="before")
    @classmethod
    def strip_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @model_validator(mode="after")
    def validate_order_shape(self):
        if self.order_type == "pickup":
            if self.organization_id is None and self.organization_slug is None:
                raise ValueError("organizationId or organizationSlug is required for pickup")
            if self.delivery_point is not None:
                raise ValueError("deliveryPoint is only allowed for delivery")
            return self

        if self.organization_id is not None or self.organization_slug is not None:
            raise ValueError("Delivery organization is selected by the backend")
        if self.delivery_point is None:
            raise ValueError("deliveryPoint is required for delivery")
        return self


class IikoOrderInfoOut(BaseModel):
    id: str | None = None
    pos_id: str | None = Field(default=None, serialization_alias="posId")
    external_number: str | None = Field(default=None, serialization_alias="externalNumber")
    creation_status: str = Field(serialization_alias="creationStatus")
    error_info: dict[str, Any] | None = Field(default=None, serialization_alias="errorInfo")


class PaymentInitOut(BaseModel):
    id: UUID
    status: str
    amount: float
    amount_kopecks: int = Field(serialization_alias="amountKopecks")
    bank_order_id: str = Field(serialization_alias="bankOrderId")
    bank_payment_id: str | None = Field(default=None, serialization_alias="bankPaymentId")
    payment_url: str = Field(serialization_alias="paymentUrl")


class CustomerOrderPaymentOut(BaseModel):
    id: UUID
    status: str
    amount: float
    amount_kopecks: int = Field(serialization_alias="amountKopecks")
    bank_order_id: str = Field(serialization_alias="bankOrderId")
    bank_payment_id: str | None = Field(default=None, serialization_alias="bankPaymentId")
    payment_url: str = Field(serialization_alias="paymentUrl")


class OrderCreateOut(BaseModel):
    id: UUID
    public_number: str = Field(serialization_alias="publicNumber")
    customer_id: UUID | None = Field(default=None, serialization_alias="customerId")
    organization_id: UUID = Field(serialization_alias="organizationId")
    organization_slug: str = Field(serialization_alias="organizationSlug")
    iiko_organization_id: str = Field(serialization_alias="iikoOrganizationId")
    terminal_group_id: str | None = Field(default=None, serialization_alias="terminalGroupId")
    order_type: OrderKind = Field(serialization_alias="orderType")
    iiko_order_type_id: str | None = Field(default=None, serialization_alias="iikoOrderTypeId")
    iiko_order_service_type: str | None = Field(default=None, serialization_alias="iikoOrderServiceType")
    payment_status: str = Field(serialization_alias="paymentStatus")
    total_sum: float = Field(serialization_alias="totalSum")
    delivery: dict[str, Any] | None = None
    payment: PaymentInitOut


class OrderStatusOut(BaseModel):
    id: UUID | None = None
    public_number: str | None = Field(default=None, serialization_alias="publicNumber")
    correlation_id: str | None = Field(default=None, serialization_alias="correlationId")
    organization_id: UUID = Field(serialization_alias="organizationId")
    organization_slug: str = Field(serialization_alias="organizationSlug")
    iiko_organization_id: str = Field(serialization_alias="iikoOrganizationId")
    order_type: OrderKind | None = Field(default=None, serialization_alias="orderType")
    iiko_order_id: str | None = Field(default=None, serialization_alias="iikoOrderId")
    creation_status: str | None = Field(default=None, serialization_alias="creationStatus")
    order_status: DeliveryStatus | str | None = Field(default=None, serialization_alias="orderStatus")
    payment_status: str | None = Field(default=None, serialization_alias="paymentStatus")
    payment_amount_kopecks: int | None = Field(default=None, serialization_alias="paymentAmountKopecks")
    number: int | None = None
    sum: float | None = None
    complete_before: str | None = Field(default=None, serialization_alias="completeBefore")
    comment: str | None = None
    notification_event: OrderNotificationEvent | None = Field(default=None, serialization_alias="notificationEvent")
    should_notify_customer: bool = Field(serialization_alias="shouldNotifyCustomer")
    error_info: dict[str, Any] | None = Field(default=None, serialization_alias="errorInfo")


class OrderStoredOut(BaseModel):
    id: UUID
    public_number: str = Field(serialization_alias="publicNumber")
    customer_id: UUID | None = Field(default=None, serialization_alias="customerId")
    organization_id: UUID = Field(serialization_alias="organizationId")
    organization_slug: str = Field(serialization_alias="organizationSlug")
    iiko_organization_id: str = Field(serialization_alias="iikoOrganizationId")
    terminal_group_id: str | None = Field(default=None, serialization_alias="terminalGroupId")
    order_type: OrderKind = Field(serialization_alias="orderType")
    iiko_order_type_id: str | None = Field(default=None, serialization_alias="iikoOrderTypeId")
    iiko_order_service_type: str | None = Field(default=None, serialization_alias="iikoOrderServiceType")
    phone: str
    comment: str | None
    complete_before: datetime | None = Field(default=None, serialization_alias="completeBefore")
    guests_count: int = Field(serialization_alias="guestsCount")
    delivery_point: dict[str, Any] | None = Field(default=None, serialization_alias="deliveryPoint")
    items: list[Any]
    iiko_order_payload: dict[str, Any] = Field(serialization_alias="iikoOrderPayload")
    payment_status: str = Field(serialization_alias="paymentStatus")
    payment_amount_kopecks: int | None = Field(default=None, serialization_alias="paymentAmountKopecks")
    payment_error_info: dict[str, Any] | None = Field(default=None, serialization_alias="paymentErrorInfo")
    iiko_correlation_id: str | None = Field(default=None, serialization_alias="iikoCorrelationId")
    iiko_order_id: str | None = Field(default=None, serialization_alias="iikoOrderId")
    iiko_pos_id: str | None = Field(default=None, serialization_alias="iikoPosId")
    iiko_external_number: str | None = Field(default=None, serialization_alias="iikoExternalNumber")
    creation_status: str | None = Field(default=None, serialization_alias="creationStatus")
    order_status: str | None = Field(default=None, serialization_alias="orderStatus")
    notification_event: OrderNotificationEvent | None = Field(default=None, serialization_alias="notificationEvent")
    total_sum: float | None = Field(default=None, serialization_alias="totalSum")
    error_info: dict[str, Any] | None = Field(default=None, serialization_alias="errorInfo")
    iiko_create_response: dict[str, Any] | None = Field(default=None, serialization_alias="iikoCreateResponse")
    iiko_status_response: dict[str, Any] | None = Field(default=None, serialization_alias="iikoStatusResponse")
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")

    model_config = ConfigDict(from_attributes=True)


class CustomerOrderOut(BaseModel):
    id: UUID
    public_number: str = Field(serialization_alias="publicNumber")
    organization_id: UUID = Field(serialization_alias="organizationId")
    organization_slug: str = Field(serialization_alias="organizationSlug")
    order_type: OrderKind = Field(serialization_alias="orderType")
    phone: str
    comment: str | None
    complete_before: datetime | None = Field(default=None, serialization_alias="completeBefore")
    guests_count: int = Field(serialization_alias="guestsCount")
    delivery_point: dict[str, Any] | None = Field(default=None, serialization_alias="deliveryPoint")
    items: list[Any]
    payment_status: str = Field(serialization_alias="paymentStatus")
    payment_amount_kopecks: int | None = Field(default=None, serialization_alias="paymentAmountKopecks")
    payment: CustomerOrderPaymentOut | None = None
    iiko_order_id: str | None = Field(default=None, serialization_alias="iikoOrderId")
    iiko_external_number: str | None = Field(default=None, serialization_alias="iikoExternalNumber")
    creation_status: str | None = Field(default=None, serialization_alias="creationStatus")
    order_status: str | None = Field(default=None, serialization_alias="orderStatus")
    notification_event: OrderNotificationEvent | None = Field(default=None, serialization_alias="notificationEvent")
    total_sum: float | None = Field(default=None, serialization_alias="totalSum")
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")

    model_config = ConfigDict(from_attributes=True)


class PaymentEventOut(BaseModel):
    id: UUID
    payment_id: UUID | None = Field(default=None, serialization_alias="paymentId")
    order_id: UUID | None = Field(default=None, serialization_alias="orderId")
    terminal_key: str | None = Field(default=None, serialization_alias="terminalKey")
    bank_order_id: str | None = Field(default=None, serialization_alias="bankOrderId")
    bank_payment_id: str | None = Field(default=None, serialization_alias="bankPaymentId")
    event_type: str = Field(serialization_alias="eventType")
    status: str | None
    success: bool | None
    token_valid: bool | None = Field(default=None, serialization_alias="tokenValid")
    processed: bool
    raw_payload: dict[str, Any] = Field(serialization_alias="rawPayload")
    error_info: dict[str, Any] | None = Field(default=None, serialization_alias="errorInfo")
    created_at: datetime = Field(serialization_alias="createdAt")

    model_config = ConfigDict(from_attributes=True)
