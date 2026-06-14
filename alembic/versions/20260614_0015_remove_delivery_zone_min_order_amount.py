"""remove delivery zone min order amount

Revision ID: 20260614_0015
Revises: 20260613_0014
Create Date: 2026-06-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260614_0015"
down_revision: Union[str, Sequence[str], None] = "20260613_0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_delivery_zones_min_order_non_negative",
        "delivery_zones",
        type_="check",
    )
    op.drop_column("delivery_zones", "min_order_amount")


def downgrade() -> None:
    op.add_column("delivery_zones", sa.Column("min_order_amount", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_delivery_zones_min_order_non_negative",
        "delivery_zones",
        "min_order_amount IS NULL OR min_order_amount >= 0",
    )
