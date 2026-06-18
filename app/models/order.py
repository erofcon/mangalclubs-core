from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin


class Order(Base, IdMixin, TimestampMixin):
    __tablename__ = "orders"

    public_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="SET NULL"),
        index=True,
    )
    organization_slug: Mapped[str] = mapped_column(String(64), nullable=False)
    iiko_organization_id: Mapped[str] = mapped_column(String(64), nullable=False)
    terminal_group_id: Mapped[str | None] = mapped_column(String(64))
    order_type: Mapped[str] = mapped_column(String(16), nullable=False)
    iiko_order_type_id: Mapped[str | None] = mapped_column(String(64))
    iiko_order_service_type: Mapped[str | None] = mapped_column(String(64))

    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    complete_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    guests_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    delivery_point: Mapped[dict | None] = mapped_column(JSON)
    items: Mapped[list] = mapped_column(JSON, nullable=False)
    iiko_order_payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    payment_status: Mapped[str] = mapped_column(String(32), default="payment_pending", nullable=False, index=True)
    payment_amount_kopecks: Mapped[int | None] = mapped_column(Integer)
    payment_error_info: Mapped[dict | None] = mapped_column(JSON)

    iiko_correlation_id: Mapped[str | None] = mapped_column(String(64))
    iiko_order_id: Mapped[str | None] = mapped_column(String(64), index=True)
    iiko_pos_id: Mapped[str | None] = mapped_column(String(64))
    iiko_external_number: Mapped[str | None] = mapped_column(String(64))
    creation_status: Mapped[str | None] = mapped_column(String(32), index=True)
    order_status: Mapped[str | None] = mapped_column(String(32), index=True)
    notification_event: Mapped[str | None] = mapped_column(String(32))
    total_sum: Mapped[float | None] = mapped_column(Numeric(12, 2))
    error_info: Mapped[dict | None] = mapped_column(JSON)
    iiko_create_response: Mapped[dict | None] = mapped_column(JSON)
    iiko_status_response: Mapped[dict | None] = mapped_column(JSON)

    organization = relationship("Organization", back_populates="orders")
    customer = relationship("Customer", back_populates="orders")
    payments = relationship(
        "TBankPayment",
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="TBankPayment.created_at.desc()",
    )

    __table_args__ = (
        Index("ix_orders_created_at", "created_at"),
        Index("ix_orders_customer_created_at", "customer_id", "created_at"),
        Index("ix_orders_organization_created_at", "organization_id", "created_at"),
    )


class TBankPayment(Base, IdMixin, TimestampMixin):
    __tablename__ = "tbank_payments"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    terminal_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    bank_order_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    bank_payment_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    amount_kopecks: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="init_requested", nullable=False, index=True)
    payment_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    init_request: Mapped[dict | None] = mapped_column(JSON)
    init_response: Mapped[dict | None] = mapped_column(JSON)
    last_notification: Mapped[dict | None] = mapped_column(JSON)
    error_info: Mapped[dict | None] = mapped_column(JSON)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    order = relationship("Order", back_populates="payments")
    organization = relationship("Organization")
    events = relationship(
        "TBankPaymentEvent",
        back_populates="payment",
        cascade="all, delete-orphan",
        order_by="TBankPaymentEvent.created_at.desc()",
    )

    __table_args__ = (
        Index("ix_tbank_payments_order_active", "order_id", "is_active"),
        Index("ix_tbank_payments_status_created_at", "status", "created_at"),
    )


class TBankPaymentEvent(Base, IdMixin, TimestampMixin):
    __tablename__ = "tbank_payment_events"

    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbank_payments.id", ondelete="SET NULL"),
        index=True,
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="SET NULL"),
        index=True,
    )
    terminal_key: Mapped[str | None] = mapped_column(String(64), index=True)
    bank_order_id: Mapped[str | None] = mapped_column(String(64), index=True)
    bank_payment_id: Mapped[str | None] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str | None] = mapped_column(String(32), index=True)
    success: Mapped[bool | None] = mapped_column(Boolean)
    token_valid: Mapped[bool | None] = mapped_column(Boolean)
    processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    raw_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    error_info: Mapped[dict | None] = mapped_column(JSON)

    payment = relationship("TBankPayment", back_populates="events")


class CustomerOrderNotification(Base, IdMixin, TimestampMixin):
    __tablename__ = "customer_order_notifications"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    push_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    push_error: Mapped[dict | None] = mapped_column(JSON)

    customer = relationship("Customer")
    order = relationship("Order")

    __table_args__ = (
        Index(
            "uq_customer_order_notifications_order_event",
            "order_id",
            "event_type",
            unique=True,
        ),
        Index("ix_customer_order_notifications_customer_unread", "customer_id", "is_read"),
    )
