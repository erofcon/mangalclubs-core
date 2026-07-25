"""add manually configured delivery zone time

Revision ID: 20260725_0022
Revises: 20260724_0021
Create Date: 2026-07-25

Existing zones keep the delivery time that the storefront previously derived
from their distance range. The migration only adds and fills a new column;
it neither removes nor changes any delivery-zone rows.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260725_0022"
down_revision: Union[str, Sequence[str], None] = "20260724_0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("delivery_zones", sa.Column("delivery_time", sa.String(length=64), nullable=True))
    op.execute(
        """
        UPDATE delivery_zones
        SET delivery_time = CASE
            WHEN distance_to_km IS NULL OR distance_to_km <= 3 THEN 'от 45 минут'
            ELSE 'от ' || trim(trailing '.' FROM trim(trailing '0' FROM
                (45 + (distance_to_km - 3) * 5)::text
            )) || ' минут'
        END
        WHERE delivery_time IS NULL
        """
    )
    op.alter_column(
        "delivery_zones",
        "delivery_time",
        existing_type=sa.String(length=64),
        nullable=False,
    )
    op.create_check_constraint(
        "ck_delivery_zones_delivery_time_not_blank",
        "delivery_zones",
        "length(btrim(delivery_time)) > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_delivery_zones_delivery_time_not_blank",
        "delivery_zones",
        type_="check",
    )
    op.drop_column("delivery_zones", "delivery_time")
