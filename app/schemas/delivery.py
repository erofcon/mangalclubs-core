from decimal import Decimal
from math import isfinite
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


class DeliveryZoneBase(BaseModel):
    distance_from_km: Decimal = Field(ge=0, max_digits=6, decimal_places=2)
    distance_to_km: Decimal | None = Field(default=None, gt=0, max_digits=6, decimal_places=2)
    price: int = Field(ge=0)
    delivery_time: str = Field(min_length=1, max_length=64)

    @field_validator("delivery_time")
    @classmethod
    def normalize_delivery_time(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("delivery_time must not be blank")

        return value

    @model_validator(mode="after")
    def validate_distance_range(self):
        if self.distance_to_km is not None and self.distance_to_km <= self.distance_from_km:
            raise ValueError("distance_to_km must be greater than distance_from_km")

        return self


class DeliveryZoneCreate(DeliveryZoneBase):
    pass


class DeliveryZoneUpdate(BaseModel):
    distance_from_km: Decimal | None = Field(default=None, ge=0, max_digits=6, decimal_places=2)
    distance_to_km: Decimal | None = Field(default=None, gt=0, max_digits=6, decimal_places=2)
    price: int | None = Field(default=None, ge=0)
    delivery_time: str = Field(default=None, min_length=1, max_length=64)

    @field_validator("delivery_time")
    @classmethod
    def normalize_delivery_time(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("delivery_time must not be blank")

        return value


class DeliveryZoneOut(BaseModel):
    id: UUID
    distance_from_km: float
    distance_to_km: float | None
    price: int
    delivery_time: str

    model_config = ConfigDict(from_attributes=True)


class DeliveryCoordinatesIn(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

    @field_validator("latitude", "longitude")
    @classmethod
    def validate_finite_coordinate(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("coordinate must be finite")
        return value


class DeliveryCheckIn(BaseModel):
    coordinates: DeliveryCoordinatesIn
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

    model_config = ConfigDict(populate_by_name=True)


class DeliveryAreaOut(BaseModel):
    type: str
    coordinates: list


class DeliveryResolvedAddressOut(BaseModel):
    formatted: str | None = None
    country: str | None = None
    country_code: str | None = Field(default=None, serialization_alias="countryCode")
    region: str | None = None
    city: str | None = None
    district: str | None = None
    suburb: str | None = None
    street: str | None = None
    house: str | None = None
    postcode: str | None = None
    place_id: str | None = Field(default=None, serialization_alias="placeId")
    source: str = "geoapify"


class DeliveryCalculationOut(BaseModel):
    available: bool
    reason: str | None = None
    distance_km: float = Field(serialization_alias="distanceKm")
    price: int | None
    zone: DeliveryZoneOut | None = None
    address: DeliveryResolvedAddressOut | None = None


class DeliverySettingsOut(BaseModel):
    delivery_area: DeliveryAreaOut = Field(serialization_alias="deliveryArea")
    pricing_zones: list[DeliveryZoneOut] = Field(serialization_alias="pricingZones")
    yandex_maps_api_key: str | None = Field(default=None, serialization_alias="yandexMapsApiKey")
