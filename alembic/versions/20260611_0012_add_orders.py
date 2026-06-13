"""add orders

Revision ID: 20260611_0012
Revises: 735fa1979b2d
Create Date: 2026-06-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260611_0012"
down_revision: Union[str, Sequence[str], None] = "735fa1979b2d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("organization_slug", sa.String(length=64), nullable=False),
        sa.Column("iiko_organization_id", sa.String(length=64), nullable=False),
        sa.Column("terminal_group_id", sa.String(length=64), nullable=True),
        sa.Column("order_type", sa.String(length=16), nullable=False),
        sa.Column("iiko_order_type_id", sa.String(length=64), nullable=True),
        sa.Column("iiko_order_service_type", sa.String(length=64), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("complete_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("guests_count", sa.Integer(), nullable=False),
        sa.Column("delivery_point", sa.JSON(), nullable=True),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("iiko_order_payload", sa.JSON(), nullable=False),
        sa.Column("iiko_correlation_id", sa.String(length=64), nullable=True),
        sa.Column("iiko_order_id", sa.String(length=64), nullable=True),
        sa.Column("iiko_pos_id", sa.String(length=64), nullable=True),
        sa.Column("iiko_external_number", sa.String(length=64), nullable=True),
        sa.Column("creation_status", sa.String(length=32), nullable=True),
        sa.Column("order_status", sa.String(length=32), nullable=True),
        sa.Column("notification_event", sa.String(length=32), nullable=True),
        sa.Column("total_sum", sa.Numeric(12, 2), nullable=True),
        sa.Column("error_info", sa.JSON(), nullable=True),
        sa.Column("iiko_create_response", sa.JSON(), nullable=True),
        sa.Column("iiko_status_response", sa.JSON(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_orders_created_at", "orders", ["created_at"], unique=False)
    op.create_index("ix_orders_iiko_order_id", "orders", ["iiko_order_id"], unique=False)
    op.create_index("ix_orders_creation_status", "orders", ["creation_status"], unique=False)
    op.create_index("ix_orders_order_status", "orders", ["order_status"], unique=False)
    op.create_index("ix_orders_organization_created_at", "orders", ["organization_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_orders_organization_created_at", table_name="orders")
    op.drop_index("ix_orders_order_status", table_name="orders")
    op.drop_index("ix_orders_creation_status", table_name="orders")
    op.drop_index("ix_orders_iiko_order_id", table_name="orders")
    op.drop_index("ix_orders_created_at", table_name="orders")
    op.drop_table("orders")
