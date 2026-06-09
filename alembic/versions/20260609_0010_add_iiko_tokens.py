"""add iiko tokens

Revision ID: 20260609_0010
Revises: 20260609_0009
Create Date: 2026-06-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260609_0010"
down_revision: Union[str, Sequence[str], None] = "20260609_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("iiko_api_login", sa.String(length=128), nullable=True))
    op.create_index(op.f("ix_organizations_iiko_api_login"), "organizations", ["iiko_api_login"], unique=True)

    op.create_table(
        "iiko_tokens",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id"),
    )
    op.create_index(op.f("ix_iiko_tokens_expires_at"), "iiko_tokens", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_iiko_tokens_expires_at"), table_name="iiko_tokens")
    op.drop_table("iiko_tokens")
    op.drop_index(op.f("ix_organizations_iiko_api_login"), table_name="organizations")
    op.drop_column("organizations", "iiko_api_login")
