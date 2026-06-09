"""add booking image orientation

Revision ID: 20260609_0009
Revises: 20260605_0008
Create Date: 2026-06-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260609_0009"
down_revision: Union[str, Sequence[str], None] = "20260605_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "booking_images",
        sa.Column(
            "orientation",
            sa.String(length=16),
            nullable=False,
            server_default="horizontal",
        ),
    )
    op.create_check_constraint(
        "ck_booking_images_orientation",
        "booking_images",
        "orientation IN ('horizontal', 'vertical')",
    )
    op.alter_column("booking_images", "orientation", server_default=None)


def downgrade() -> None:
    op.drop_constraint("ck_booking_images_orientation", "booking_images", type_="check")
    op.drop_column("booking_images", "orientation")
