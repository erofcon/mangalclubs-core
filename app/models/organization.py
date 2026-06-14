from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
import uuid

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Numeric, SmallInteger, String, Text, Time, UniqueConstraint
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
    iiko_api_login: Mapped[str | None] = mapped_column(String(128), index=True)
    iiko_organization_id: Mapped[str | None] = mapped_column(String(64), index=True)
    iiko_online_payment_type_id: Mapped[str | None] = mapped_column(String(64))
    iiko_online_payment_type_kind: Mapped[str] = mapped_column(String(32), default="Card", nullable=False)
    tbank_terminal_key: Mapped[str | None] = mapped_column(String(64), index=True)
    tbank_password: Mapped[str | None] = mapped_column(Text)
    accepts_pickup: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    accepts_delivery: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_default_delivery: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    working_hours: Mapped[list[OrganizationWorkingHour]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
        order_by="OrganizationWorkingHour.weekday",
    )
    booking_categories: Mapped[list[BookingCategory]] = relationship(
        "BookingCategory",
        back_populates="organization",
        cascade="all, delete-orphan",
        order_by="BookingCategory.sort_order",
    )
    bookings: Mapped[list[Booking]] = relationship(
        "Booking",
        back_populates="organization",
        cascade="all, delete-orphan",
        order_by="Booking.sort_order",
    )
    iiko_token: Mapped[IikoToken | None] = relationship(
        "IikoToken",
        back_populates="organization",
        cascade="all, delete-orphan",
        uselist=False,
    )
    iiko_menu_snapshot: Mapped[IikoMenuSnapshot | None] = relationship(
        "IikoMenuSnapshot",
        back_populates="organization",
        cascade="all, delete-orphan",
        uselist=False,
    )
    orders: Mapped[list[Order]] = relationship(
        "Order",
        back_populates="organization",
        order_by="Order.created_at.desc()",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint("latitude >= -90 AND latitude <= 90", name="ck_organizations_latitude_range"),
        CheckConstraint("longitude >= -180 AND longitude <= 180", name="ck_organizations_longitude_range"),
    )

    @property
    def coordinates(self) -> dict[str, Decimal]:
        return {"latitude": self.latitude, "longitude": self.longitude}

    @property
    def payment_configured(self) -> bool:
        return bool(self.tbank_terminal_key and self.tbank_password)


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


class IikoToken(Base, IdMixin, TimestampMixin):
    __tablename__ = "iiko_tokens"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    access_token: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    organization: Mapped[Organization] = relationship(back_populates="iiko_token")
