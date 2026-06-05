"""add bookings

Revision ID: 20260605_0006
Revises: 20260605_0005
Create Date: 2026-06-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260605_0006"
down_revision: Union[str, Sequence[str], None] = "20260605_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "booking_categories",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("preview_url", sa.String(length=1024), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "title", name="uq_booking_categories_organization_title"),
    )
    op.create_index(
        "ix_booking_categories_organization_sort",
        "booking_categories",
        ["organization_id", "sort_order"],
        unique=False,
    )

    op.create_table(
        "bookings",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("category_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("long_description", sa.Text(), nullable=True),
        sa.Column("preview_url", sa.String(length=1024), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["category_id"], ["booking_categories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "category_id", "title", name="uq_bookings_organization_category_title"),
    )
    op.create_index("ix_bookings_category_sort", "bookings", ["category_id", "sort_order"], unique=False)
    op.create_index("ix_bookings_organization_sort", "bookings", ["organization_id", "sort_order"], unique=False)

    op.create_table(
        "booking_images",
        sa.Column("booking_id", sa.UUID(), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("alt_text", sa.String(length=255), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_booking_images_booking_sort", "booking_images", ["booking_id", "sort_order"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_booking_images_booking_sort", table_name="booking_images")
    op.drop_table("booking_images")
    op.drop_index("ix_bookings_organization_sort", table_name="bookings")
    op.drop_index("ix_bookings_category_sort", table_name="bookings")
    op.drop_table("bookings")
    op.drop_index("ix_booking_categories_organization_sort", table_name="booking_categories")
    op.drop_table("booking_categories")
