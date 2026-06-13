"""add customer profile

Revision ID: 20260612_0013
Revises: 20260611_0012
Create Date: 2026-06-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260612_0013"
down_revision: Union[str, Sequence[str], None] = "20260611_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("email", sa.String(length=255), nullable=True))
    op.add_column("customers", sa.Column("birthday", sa.Date(), nullable=True))
    op.add_column("customers", sa.Column("avatar_url", sa.String(length=1024), nullable=True))
    op.create_index(op.f("ix_customers_email"), "customers", ["email"], unique=True)

    op.add_column("orders", sa.Column("customer_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_orders_customer_id"), "orders", ["customer_id"], unique=False)
    op.create_index("ix_orders_customer_created_at", "orders", ["customer_id", "created_at"], unique=False)
    op.create_foreign_key(
        "fk_orders_customer_id_customers",
        "orders",
        "customers",
        ["customer_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_orders_customer_id_customers", "orders", type_="foreignkey")
    op.drop_index("ix_orders_customer_created_at", table_name="orders")
    op.drop_index(op.f("ix_orders_customer_id"), table_name="orders")
    op.drop_column("orders", "customer_id")

    op.drop_index(op.f("ix_customers_email"), table_name="customers")
    op.drop_column("customers", "avatar_url")
    op.drop_column("customers", "birthday")
    op.drop_column("customers", "email")
