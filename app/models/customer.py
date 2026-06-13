from datetime import date

from sqlalchemy import Boolean, Date, String
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

    orders = relationship("Order", back_populates="customer")
