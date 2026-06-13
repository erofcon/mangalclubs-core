"""add tbank payments

Revision ID: 20260613_0014
Revises: 20260612_0013
Create Date: 2026-06-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260613_0014"
down_revision: Union[str, Sequence[str], None] = "20260612_0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("iiko_online_payment_type_id", sa.String(length=64), nullable=True))
    op.add_column(
        "organizations",
        sa.Column("iiko_online_payment_type_kind", sa.String(length=32), nullable=False, server_default="Card"),
    )
    op.add_column("organizations", sa.Column("tbank_terminal_key", sa.String(length=64), nullable=True))
    op.add_column("organizations", sa.Column("tbank_password", sa.Text(), nullable=True))
    op.create_index(op.f("ix_organizations_tbank_terminal_key"), "organizations", ["tbank_terminal_key"], unique=False)

    op.add_column(
        "orders",
        sa.Column("payment_status", sa.String(length=32), nullable=False, server_default="payment_pending"),
    )
    op.add_column("orders", sa.Column("payment_amount_kopecks", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("payment_error_info", sa.JSON(), nullable=True))
    op.create_index(op.f("ix_orders_payment_status"), "orders", ["payment_status"], unique=False)

    op.create_table(
        "tbank_payments",
        sa.Column("order_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("terminal_key", sa.String(length=64), nullable=False),
        sa.Column("bank_order_id", sa.String(length=64), nullable=False),
        sa.Column("bank_payment_id", sa.String(length=64), nullable=True),
        sa.Column("amount_kopecks", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payment_url", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("init_request", sa.JSON(), nullable=True),
        sa.Column("init_response", sa.JSON(), nullable=True),
        sa.Column("last_notification", sa.JSON(), nullable=True),
        sa.Column("error_info", sa.JSON(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bank_order_id"),
        sa.UniqueConstraint("bank_payment_id"),
    )
    op.create_index(op.f("ix_tbank_payments_order_id"), "tbank_payments", ["order_id"], unique=False)
    op.create_index(op.f("ix_tbank_payments_organization_id"), "tbank_payments", ["organization_id"], unique=False)
    op.create_index(op.f("ix_tbank_payments_terminal_key"), "tbank_payments", ["terminal_key"], unique=False)
    op.create_index(op.f("ix_tbank_payments_bank_payment_id"), "tbank_payments", ["bank_payment_id"], unique=False)
    op.create_index(op.f("ix_tbank_payments_status"), "tbank_payments", ["status"], unique=False)
    op.create_index(op.f("ix_tbank_payments_paid_at"), "tbank_payments", ["paid_at"], unique=False)
    op.create_index("ix_tbank_payments_order_active", "tbank_payments", ["order_id", "is_active"], unique=False)
    op.create_index(
        "ix_tbank_payments_status_created_at",
        "tbank_payments",
        ["status", "created_at"],
        unique=False,
    )

    op.create_table(
        "tbank_payment_events",
        sa.Column("payment_id", sa.UUID(), nullable=True),
        sa.Column("order_id", sa.UUID(), nullable=True),
        sa.Column("terminal_key", sa.String(length=64), nullable=True),
        sa.Column("bank_order_id", sa.String(length=64), nullable=True),
        sa.Column("bank_payment_id", sa.String(length=64), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=True),
        sa.Column("token_valid", sa.Boolean(), nullable=True),
        sa.Column("processed", sa.Boolean(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("error_info", sa.JSON(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["payment_id"], ["tbank_payments.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tbank_payment_events_payment_id"), "tbank_payment_events", ["payment_id"], unique=False)
    op.create_index(op.f("ix_tbank_payment_events_order_id"), "tbank_payment_events", ["order_id"], unique=False)
    op.create_index(op.f("ix_tbank_payment_events_terminal_key"), "tbank_payment_events", ["terminal_key"], unique=False)
    op.create_index(op.f("ix_tbank_payment_events_bank_order_id"), "tbank_payment_events", ["bank_order_id"], unique=False)
    op.create_index(
        op.f("ix_tbank_payment_events_bank_payment_id"),
        "tbank_payment_events",
        ["bank_payment_id"],
        unique=False,
    )
    op.create_index(op.f("ix_tbank_payment_events_event_type"), "tbank_payment_events", ["event_type"], unique=False)
    op.create_index(op.f("ix_tbank_payment_events_status"), "tbank_payment_events", ["status"], unique=False)
    op.create_index(op.f("ix_tbank_payment_events_processed"), "tbank_payment_events", ["processed"], unique=False)

    op.alter_column("organizations", "iiko_online_payment_type_kind", server_default=None)
    op.alter_column("orders", "payment_status", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_tbank_payment_events_processed"), table_name="tbank_payment_events")
    op.drop_index(op.f("ix_tbank_payment_events_status"), table_name="tbank_payment_events")
    op.drop_index(op.f("ix_tbank_payment_events_event_type"), table_name="tbank_payment_events")
    op.drop_index(op.f("ix_tbank_payment_events_bank_payment_id"), table_name="tbank_payment_events")
    op.drop_index(op.f("ix_tbank_payment_events_bank_order_id"), table_name="tbank_payment_events")
    op.drop_index(op.f("ix_tbank_payment_events_terminal_key"), table_name="tbank_payment_events")
    op.drop_index(op.f("ix_tbank_payment_events_order_id"), table_name="tbank_payment_events")
    op.drop_index(op.f("ix_tbank_payment_events_payment_id"), table_name="tbank_payment_events")
    op.drop_table("tbank_payment_events")

    op.drop_index("ix_tbank_payments_status_created_at", table_name="tbank_payments")
    op.drop_index("ix_tbank_payments_order_active", table_name="tbank_payments")
    op.drop_index(op.f("ix_tbank_payments_paid_at"), table_name="tbank_payments")
    op.drop_index(op.f("ix_tbank_payments_status"), table_name="tbank_payments")
    op.drop_index(op.f("ix_tbank_payments_bank_payment_id"), table_name="tbank_payments")
    op.drop_index(op.f("ix_tbank_payments_terminal_key"), table_name="tbank_payments")
    op.drop_index(op.f("ix_tbank_payments_organization_id"), table_name="tbank_payments")
    op.drop_index(op.f("ix_tbank_payments_order_id"), table_name="tbank_payments")
    op.drop_table("tbank_payments")

    op.drop_index(op.f("ix_orders_payment_status"), table_name="orders")
    op.drop_column("orders", "payment_error_info")
    op.drop_column("orders", "payment_amount_kopecks")
    op.drop_column("orders", "payment_status")

    op.drop_index(op.f("ix_organizations_tbank_terminal_key"), table_name="organizations")
    op.drop_column("organizations", "tbank_password")
    op.drop_column("organizations", "tbank_terminal_key")
    op.drop_column("organizations", "iiko_online_payment_type_kind")
    op.drop_column("organizations", "iiko_online_payment_type_id")
