"""remove iiko customer id

Revision ID: 20260519_0002
Revises: 3e30f6988dc3
Create Date: 2026-05-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260519_0002"
down_revision: Union[str, Sequence[str], None] = "3e30f6988dc3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index(op.f("ix_customers_iiko_customer_id"), table_name="customers")
    op.drop_column("customers", "iiko_customer_id")


def downgrade() -> None:
    op.add_column("customers", sa.Column("iiko_customer_id", sa.String(length=128), nullable=True))
    op.create_index(op.f("ix_customers_iiko_customer_id"), "customers", ["iiko_customer_id"], unique=True)
