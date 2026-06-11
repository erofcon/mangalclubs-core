"""fix booking preview url column

Revision ID: 20260608_0009
Revises: 20260605_0008
Create Date: 2026-06-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260608_0009"
down_revision: Union[str, Sequence[str], None] = "20260605_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _bookings_columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns("bookings")}


def upgrade() -> None:
    columns = _bookings_columns()

    if "preview_url" in columns:
        return

    if "photo_url" in columns:
        op.alter_column(
            "bookings",
            "photo_url",
            new_column_name="preview_url",
            existing_type=sa.String(length=1024),
            existing_nullable=True,
        )
        return

    op.add_column("bookings", sa.Column("preview_url", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    columns = _bookings_columns()

    if "photo_url" in columns or "preview_url" not in columns:
        return

    op.alter_column(
        "bookings",
        "preview_url",
        new_column_name="photo_url",
        existing_type=sa.String(length=1024),
        existing_nullable=True,
    )
