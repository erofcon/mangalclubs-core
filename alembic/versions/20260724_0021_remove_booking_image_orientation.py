"""remove booking image orientation

Revision ID: 20260724_0021
Revises: 20260618_0020
Create Date: 2026-07-24

The orientation only split the same gallery into two API fields.  Dropping it
does not delete or alter any booking_images rows, so existing cabin galleries
remain intact.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260724_0021"
down_revision: Union[str, Sequence[str], None] = "20260618_0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE booking_images DROP CONSTRAINT IF EXISTS ck_booking_images_orientation")
    op.execute("ALTER TABLE booking_images DROP COLUMN IF EXISTS orientation")


def downgrade() -> None:
    op.add_column(
        "booking_images",
        sa.Column("orientation", sa.String(length=16), nullable=False, server_default="horizontal"),
    )
    op.create_check_constraint(
        "ck_booking_images_orientation",
        "booking_images",
        "orientation IN ('horizontal', 'vertical')",
    )
    op.alter_column("booking_images", "orientation", server_default=None)
