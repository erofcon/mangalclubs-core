"""add customer order notifications

Revision ID: 20260617_0019
Revises: 20260615_0018
Create Date: 2026-06-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260617_0019"
down_revision: Union[str, Sequence[str], None] = "20260615_0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "customer_devices",
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", sa.String(length=128), nullable=False),
        sa.Column("push_token", sa.String(length=255), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=True),
        sa.Column("device_name", sa.String(length=255), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id", "device_id", name="uq_customer_devices_customer_device"),
    )
    op.create_index("ix_customer_devices_customer_active", "customer_devices", ["customer_id", "is_active"])
    op.create_index(op.f("ix_customer_devices_customer_id"), "customer_devices", ["customer_id"])
    op.create_index(op.f("ix_customer_devices_push_token"), "customer_devices", ["push_token"])

    op.create_table(
        "customer_order_notifications",
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("push_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("push_error", sa.JSON(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_customer_order_notifications_customer_unread",
        "customer_order_notifications",
        ["customer_id", "is_read"],
    )
    op.create_index(op.f("ix_customer_order_notifications_customer_id"), "customer_order_notifications", ["customer_id"])
    op.create_index(op.f("ix_customer_order_notifications_event_type"), "customer_order_notifications", ["event_type"])
    op.create_index(op.f("ix_customer_order_notifications_is_read"), "customer_order_notifications", ["is_read"])
    op.create_index(op.f("ix_customer_order_notifications_order_id"), "customer_order_notifications", ["order_id"])
    op.create_index(
        "uq_customer_order_notifications_order_event",
        "customer_order_notifications",
        ["order_id", "event_type"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_customer_order_notifications_order_event", table_name="customer_order_notifications")
    op.drop_index(op.f("ix_customer_order_notifications_order_id"), table_name="customer_order_notifications")
    op.drop_index(op.f("ix_customer_order_notifications_is_read"), table_name="customer_order_notifications")
    op.drop_index(op.f("ix_customer_order_notifications_event_type"), table_name="customer_order_notifications")
    op.drop_index(op.f("ix_customer_order_notifications_customer_id"), table_name="customer_order_notifications")
    op.drop_index("ix_customer_order_notifications_customer_unread", table_name="customer_order_notifications")
    op.drop_table("customer_order_notifications")

    op.drop_index(op.f("ix_customer_devices_push_token"), table_name="customer_devices")
    op.drop_index(op.f("ix_customer_devices_customer_id"), table_name="customer_devices")
    op.drop_index("ix_customer_devices_customer_active", table_name="customer_devices")
    op.drop_table("customer_devices")
