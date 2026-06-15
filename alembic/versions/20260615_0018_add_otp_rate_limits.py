"""add otp rate limits

Revision ID: 20260615_0018
Revises: 20260615_0017
Create Date: 2026-06-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260615_0018"
down_revision: Union[str, Sequence[str], None] = "20260615_0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "otp_rate_limits",
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope", "key", name="uq_otp_rate_limits_scope_key"),
    )
    op.create_index(
        op.f("ix_otp_rate_limits_blocked_until"),
        "otp_rate_limits",
        ["blocked_until"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_otp_rate_limits_blocked_until"), table_name="otp_rate_limits")
    op.drop_table("otp_rate_limits")
