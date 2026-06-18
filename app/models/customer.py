from datetime import date, datetime
import uuid

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin


class Customer(Base, IdMixin, TimestampMixin):
    __tablename__ = "customers"

    phone: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    birthday: Mapped[date | None] = mapped_column(Date)
    avatar_url: Mapped[str | None] = mapped_column(String(1024))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    orders = relationship("Order", back_populates="customer", passive_deletes=True)
    devices = relationship("CustomerDevice", back_populates="customer", cascade="all, delete-orphan")


class CustomerDevice(Base, IdMixin, TimestampMixin):
    __tablename__ = "customer_devices"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    device_id: Mapped[str] = mapped_column(String(128), nullable=False)
    push_token: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    platform: Mapped[str | None] = mapped_column(String(32))
    device_name: Mapped[str | None] = mapped_column(String(255))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    customer = relationship("Customer", back_populates="devices")

    __table_args__ = (
        UniqueConstraint("customer_id", "device_id", name="uq_customer_devices_customer_device"),
        Index("ix_customer_devices_customer_active", "customer_id", "is_active"),
    )
