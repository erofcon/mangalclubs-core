from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DeliveryZoneBase(BaseModel):
    distance_from_km: Decimal = Field(ge=0, max_digits=6, decimal_places=2)
    distance_to_km: Decimal = Field(gt=0, max_digits=6, decimal_places=2)
    min_order_amount: int | None = Field(default=None, ge=0)
    price: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_distance_range(self):
        if self.distance_to_km <= self.distance_from_km:
            raise ValueError("distance_to_km must be greater than distance_from_km")

        return self


class DeliveryZoneCreate(DeliveryZoneBase):
    pass


class DeliveryZoneUpdate(BaseModel):
    distance_from_km: Decimal | None = Field(default=None, ge=0, max_digits=6, decimal_places=2)
    distance_to_km: Decimal | None = Field(default=None, gt=0, max_digits=6, decimal_places=2)
    min_order_amount: int | None = Field(default=None, ge=0)
    price: int | None = Field(default=None, ge=0)


class DeliveryZoneOut(BaseModel):
    id: UUID
    distance_from_km: float
    distance_to_km: float
    min_order_amount: int | None
    price: int

    model_config = ConfigDict(from_attributes=True)
