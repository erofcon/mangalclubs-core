from __future__ import annotations

import enum
import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin


class StorySlideMediaType(str, enum.Enum):
    image = "image"
    video = "video"


class Story(Base, IdMixin, TimestampMixin):
    __tablename__ = "stories"

    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    preview_url: Mapped[str | None] = mapped_column(String(1024))
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    slides: Mapped[list[StorySlide]] = relationship(
        back_populates="story",
        cascade="all, delete-orphan",
        order_by="StorySlide.sort_order",
    )

    __table_args__ = (Index("ix_stories_active_sort", "is_active", "sort_order"),)


class StorySlide(Base, IdMixin, TimestampMixin):
    __tablename__ = "story_slides"

    story_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stories.id", ondelete="CASCADE"),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    media_type: Mapped[StorySlideMediaType] = mapped_column(String(16), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    caption: Mapped[str | None] = mapped_column(Text)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    story: Mapped[Story] = relationship(back_populates="slides")

    __table_args__ = (
        Index("ix_story_slides_story_active_sort", "story_id", "is_active", "sort_order"),
        CheckConstraint("media_type IN ('image', 'video')", name="ck_story_slides_media_type"),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds > 0",
            name="ck_story_slides_duration_positive",
        ),
    )
