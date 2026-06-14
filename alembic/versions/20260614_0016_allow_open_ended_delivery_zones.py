"""allow open ended delivery zones

Revision ID: 20260614_0016
Revises: 20260614_0015
Create Date: 2026-06-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260614_0016"
down_revision: Union[str, Sequence[str], None] = "20260614_0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_delivery_zones_distance_range",
        "delivery_zones",
        type_="check",
    )
    op.alter_column(
        "delivery_zones",
        "distance_to_km",
        existing_type=sa.Numeric(precision=6, scale=2),
        nullable=True,
    )
    op.create_check_constraint(
        "ck_delivery_zones_distance_range",
        "delivery_zones",
        "distance_to_km IS NULL OR distance_to_km > distance_from_km",
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM delivery_zones
        WHERE distance_to_km IS NULL
        """
    )
    op.drop_constraint(
        "ck_delivery_zones_distance_range",
        "delivery_zones",
        type_="check",
    )
    op.alter_column(
        "delivery_zones",
        "distance_to_km",
        existing_type=sa.Numeric(precision=6, scale=2),
        nullable=False,
    )
    op.create_check_constraint(
        "ck_delivery_zones_distance_range",
        "delivery_zones",
        "distance_to_km > distance_from_km",
    )
