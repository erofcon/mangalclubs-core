from __future__ import annotations

import enum
import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin


class BookingImageOrientation(str, enum.Enum):
    horizontal = "horizontal"
    vertical = "vertical"


class BookingCategory(Base, IdMixin, TimestampMixin):
    __tablename__ = "booking_categories"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    preview_url: Mapped[str | None] = mapped_column(String(1024))

    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    organization = relationship("Organization", back_populates="booking_categories")
    bookings: Mapped[list[Booking]] = relationship(
        back_populates="category",
        cascade="all, delete-orphan",
        order_by="Booking.sort_order",
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "title", name="uq_booking_categories_organization_title"),
        Index("ix_booking_categories_organization_sort", "organization_id", "sort_order"),
    )


class Booking(Base, IdMixin, TimestampMixin):
    __tablename__ = "bookings"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("booking_categories.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    long_description: Mapped[str | None] = mapped_column(Text)
    preview_url: Mapped[str | None] = mapped_column(String(1024))

    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    organization = relationship("Organization", back_populates="bookings")
    category: Mapped[BookingCategory] = relationship(back_populates="bookings")
    images: Mapped[list[BookingImage]] = relationship(
        back_populates="booking",
        cascade="all, delete-orphan",
        order_by="BookingImage.sort_order",
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "category_id", "title", name="uq_bookings_organization_category_title"),
        Index("ix_bookings_organization_sort", "organization_id", "sort_order"),
        Index("ix_bookings_category_sort", "category_id", "sort_order"),
    )


class BookingImage(Base, IdMixin, TimestampMixin):
    __tablename__ = "booking_images"

    booking_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bookings.id", ondelete="CASCADE"),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    orientation: Mapped[BookingImageOrientation] = mapped_column(
        String(16),
        default=BookingImageOrientation.horizontal.value,
        nullable=False,
    )
    alt_text: Mapped[str | None] = mapped_column(String(255))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    booking: Mapped[Booking] = relationship(back_populates="images")

    __table_args__ = (
        Index("ix_booking_images_booking_sort", "booking_id", "sort_order"),
        CheckConstraint("orientation IN ('horizontal', 'vertical')", name="ck_booking_images_orientation"),
    )
