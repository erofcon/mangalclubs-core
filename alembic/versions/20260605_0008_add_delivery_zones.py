"""add delivery zones

Revision ID: 20260605_0008
Revises: 20260605_0007
Create Date: 2026-06-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260605_0008"
down_revision: Union[str, Sequence[str], None] = "20260605_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "delivery_zones",
        sa.Column("distance_from_km", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("distance_to_km", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("min_order_amount", sa.Integer(), nullable=True),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("distance_from_km >= 0", name="ck_delivery_zones_distance_from_non_negative"),
        sa.CheckConstraint("distance_to_km > distance_from_km", name="ck_delivery_zones_distance_range"),
        sa.CheckConstraint(
            "min_order_amount IS NULL OR min_order_amount >= 0",
            name="ck_delivery_zones_min_order_non_negative",
        ),
        sa.CheckConstraint("price >= 0", name="ck_delivery_zones_price_non_negative"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_delivery_zones_distance_range",
        "delivery_zones",
        ["distance_from_km", "distance_to_km"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_delivery_zones_distance_range", table_name="delivery_zones")
    op.drop_table("delivery_zones")
