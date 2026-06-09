from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin


class IikoMenuSnapshot(Base, IdMixin, TimestampMixin):
    __tablename__ = "iiko_menu_snapshots"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    external_menu_id: Mapped[str | None] = mapped_column(String(64))
    external_menu_name: Mapped[str | None] = mapped_column(String(255))
    revision: Mapped[int | None] = mapped_column(Integer)
    raw_menu: Mapped[dict | None] = mapped_column(JSON)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    organization = relationship("Organization", back_populates="iiko_menu_snapshot")


class MenuItemContent(Base, IdMixin, TimestampMixin):
    __tablename__ = "menu_item_contents"

    iiko_item_id: Mapped[str | None] = mapped_column(String(64))
    sku: Mapped[str | None] = mapped_column(String(64))
    name_override: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(String(1024))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        Index(
            "uq_menu_item_contents_iiko_item_id",
            "iiko_item_id",
            unique=True,
            postgresql_where=iiko_item_id.is_not(None),
        ),
        Index("uq_menu_item_contents_sku", "sku", unique=True, postgresql_where=sku.is_not(None)),
        Index("ix_menu_item_contents_active_sort", "is_active", "sort_order"),
    )
