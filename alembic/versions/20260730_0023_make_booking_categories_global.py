"""make booking categories global

Revision ID: 20260730_0023
Revises: 20260725_0022
Create Date: 2026-07-30

Booking categories are shared by all organizations. Existing category rows are
kept intact; categories with matching titles can be consolidated manually.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260730_0023"
down_revision: Union[str, Sequence[str], None] = "20260725_0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_booking_categories_organization_title",
        "booking_categories",
        type_="unique",
    )
    op.drop_index("ix_booking_categories_organization_sort", table_name="booking_categories")
    op.drop_column("booking_categories", "organization_id")
    op.create_index("ix_booking_categories_sort", "booking_categories", ["sort_order"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_booking_categories_sort", table_name="booking_categories")
    op.add_column("booking_categories", sa.Column("organization_id", sa.UUID(), nullable=True))

    # A shared category cannot be losslessly converted back to organization-owned
    # categories. Associate it with the organization of its first booking instead.
    op.execute(
        """
        UPDATE booking_categories AS category
        SET organization_id = source.organization_id
        FROM (
            SELECT DISTINCT ON (category_id) category_id, organization_id
            FROM bookings
            ORDER BY category_id, created_at, id
        ) AS source
        WHERE category.id = source.category_id
        """
    )
    op.execute(
        """
        UPDATE booking_categories
        SET organization_id = (SELECT id FROM organizations ORDER BY created_at, id LIMIT 1)
        WHERE organization_id IS NULL
        """
    )
    op.alter_column("booking_categories", "organization_id", nullable=False)
    op.create_foreign_key(
        "booking_categories_organization_id_fkey",
        "booking_categories",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_booking_categories_organization_title",
        "booking_categories",
        ["organization_id", "title"],
    )
    op.create_index(
        "ix_booking_categories_organization_sort",
        "booking_categories",
        ["organization_id", "sort_order"],
        unique=False,
    )
