from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


OrderType = Literal["delivery", "pickup"]


class MenuCategoryOut(BaseModel):
    id: str
    title: str


class MenuItemOut(BaseModel):
    id: str
    sku: str | None = None
    name: str
    description: str = ""
    price: float
    image: str | None = None
    weight: str | None = None
    calories: float | None = None
    fats: float | None = None
    proteins: float | None = None
    carbs: float | None = None
    size_id: str | None = None
    size_name: str | None = None
    measure_unit_type: str | None = None
    modifiers: list[dict[str, Any]] = Field(default_factory=list)


class MenuCategoryWithItemsOut(MenuCategoryOut):
    items: list[MenuItemOut]


class MenuOut(BaseModel):
    order_type: OrderType = Field(serialization_alias="orderType")
    organization_id: UUID = Field(serialization_alias="organizationId")
    organization_slug: str = Field(serialization_alias="organizationSlug")
    iiko_organization_id: str = Field(serialization_alias="iikoOrganizationId")
    external_menu_id: str | None = Field(serialization_alias="externalMenuId")
    external_menu_name: str | None = Field(serialization_alias="externalMenuName")
    revision: int | None = None
    synced_at: datetime | None = Field(serialization_alias="syncedAt")
    is_stale: bool = Field(serialization_alias="isStale")
    categories: list[MenuCategoryOut]
    menu: list[MenuCategoryWithItemsOut]


class MenuItemContentBase(BaseModel):
    iiko_item_id: str | None = Field(default=None, min_length=1, max_length=64)
    sku: str | None = Field(default=None, min_length=1, max_length=64)
    name_override: str | None = Field(default=None, max_length=255)
    description: str | None = None
    image_url: HttpUrl | str | None = Field(default=None, max_length=1024)
    sort_order: int = 0
    is_active: bool = True

    @field_validator("iiko_item_id", "sku", "name_override", "description", "image_url", mode="before")
    @classmethod
    def strip_optional_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @model_validator(mode="after")
    def validate_binding_key(self):
        if not self.iiko_item_id and not self.sku:
            raise ValueError("iiko_item_id or sku is required")
        return self


class MenuItemContentCreate(MenuItemContentBase):
    pass


class MenuItemContentUpdate(BaseModel):
    iiko_item_id: str | None = Field(default=None, min_length=1, max_length=64)
    sku: str | None = Field(default=None, min_length=1, max_length=64)
    name_override: str | None = Field(default=None, max_length=255)
    description: str | None = None
    image_url: HttpUrl | str | None = Field(default=None, max_length=1024)
    sort_order: int | None = None
    is_active: bool | None = None

    @field_validator("iiko_item_id", "sku", "name_override", "description", "image_url", mode="before")
    @classmethod
    def strip_optional_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @model_validator(mode="after")
    def validate_non_empty_payload(self):
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        if self.iiko_item_id is None and self.sku is None and {"iiko_item_id", "sku"}.issubset(self.model_fields_set):
            raise ValueError("iiko_item_id or sku is required")
        return self


class MenuItemContentOut(BaseModel):
    id: UUID
    iiko_item_id: str | None
    sku: str | None
    name_override: str | None
    description: str | None
    image_url: str | None
    sort_order: int
    is_active: bool

    model_config = ConfigDict(from_attributes=True)
