from __future__ import annotations

from datetime import time
from decimal import Decimal
import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Numeric, SmallInteger, String, Text, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin


class Organization(Base, IdMixin, TimestampMixin):
    __tablename__ = "organizations"

    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    city: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    intro: Mapped[str] = mapped_column(Text, nullable=False)
    latitude: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    photo_url: Mapped[str | None] = mapped_column(String(1024))

    working_hours: Mapped[list[OrganizationWorkingHour]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
        order_by="OrganizationWorkingHour.weekday",
    )

    __table_args__ = (
        CheckConstraint("latitude >= -90 AND latitude <= 90", name="ck_organizations_latitude_range"),
        CheckConstraint("longitude >= -180 AND longitude <= 180", name="ck_organizations_longitude_range"),
    )

    @property
    def coordinates(self) -> dict[str, Decimal]:
        return {"latitude": self.latitude, "longitude": self.longitude}


class OrganizationWorkingHour(Base):
    __tablename__ = "organization_working_hours"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    opens_at: Mapped[time | None] = mapped_column(Time(timezone=False))
    closes_at: Mapped[time | None] = mapped_column(Time(timezone=False))

    organization: Mapped[Organization] = relationship(back_populates="working_hours")

    __table_args__ = (
        UniqueConstraint("organization_id", "weekday", name="uq_organization_working_hours_weekday"),
        CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_organization_working_hours_weekday_range"),
        CheckConstraint(
            "(is_closed = true AND opens_at IS NULL AND closes_at IS NULL) "
            "OR (is_closed = false AND opens_at IS NOT NULL AND closes_at IS NOT NULL)",
            name="ck_organization_working_hours_time_presence",
        ),
    )

    @property
    def closes_next_day(self) -> bool:
        return bool(not self.is_closed and self.opens_at and self.closes_at and self.closes_at <= self.opens_at)
