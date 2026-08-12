from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class DeliveryZone(Base, IdMixin, TimestampMixin):
    __tablename__ = "delivery_zones"

    distance_from_km: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    distance_to_km: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    # These columns already exist in some deployed databases. Keep them in
    # the ORM model even though delivery-zone ordering/activation is not
    # currently exposed by the API, otherwise PostgreSQL rejects inserts
    # because both columns are NOT NULL.
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    delivery_time: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        CheckConstraint("distance_from_km >= 0", name="ck_delivery_zones_distance_from_non_negative"),
        CheckConstraint(
            "distance_to_km IS NULL OR distance_to_km > distance_from_km",
            name="ck_delivery_zones_distance_range",
        ),
        CheckConstraint("price >= 0", name="ck_delivery_zones_price_non_negative"),
        CheckConstraint("length(btrim(delivery_time)) > 0", name="ck_delivery_zones_delivery_time_not_blank"),
        Index("ix_delivery_zones_distance_range", "distance_from_km", "distance_to_km"),
    )
