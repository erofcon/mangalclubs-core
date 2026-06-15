import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Enum, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class AuthSubjectType(str, enum.Enum):
    customer = "customer"
    staff = "staff"


class OtpChallenge(Base, IdMixin, TimestampMixin):
    __tablename__ = "otp_challenges"

    phone: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    code_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    attempts_left: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    resend_available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OtpRateLimit(Base, IdMixin, TimestampMixin):
    __tablename__ = "otp_rate_limits"

    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("scope", "key", name="uq_otp_rate_limits_scope_key"),
    )


class RefreshSession(Base, IdMixin, TimestampMixin):
    __tablename__ = "refresh_sessions"

    subject_type: Mapped[AuthSubjectType] = mapped_column(Enum(AuthSubjectType), nullable=False)
    subject_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)

    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    device_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    device_name: Mapped[str | None] = mapped_column(String(255))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_refresh_sessions_subject", "subject_type", "subject_id"),
    )
