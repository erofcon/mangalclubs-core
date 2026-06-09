"""add iiko menu

Revision ID: 20260609_0011
Revises: 20260609_0010
Create Date: 2026-06-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260609_0011"
down_revision: Union[str, Sequence[str], None] = "20260609_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_organizations_iiko_api_login")
    op.create_index(op.f("ix_organizations_iiko_api_login"), "organizations", ["iiko_api_login"], unique=False)

    op.add_column("organizations", sa.Column("iiko_organization_id", sa.String(length=64), nullable=True))
    op.add_column(
        "organizations",
        sa.Column("accepts_pickup", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "organizations",
        sa.Column("accepts_delivery", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "organizations",
        sa.Column("is_default_delivery", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(op.f("ix_organizations_iiko_organization_id"), "organizations", ["iiko_organization_id"], unique=False)
    op.create_index(
        "ix_organizations_default_delivery",
        "organizations",
        ["is_default_delivery"],
        unique=True,
        postgresql_where=sa.text("is_default_delivery = true"),
    )
    op.alter_column("organizations", "accepts_pickup", server_default=None)
    op.alter_column("organizations", "accepts_delivery", server_default=None)
    op.alter_column("organizations", "is_default_delivery", server_default=None)

    op.create_table(
        "iiko_menu_snapshots",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_menu_id", sa.String(length=64), nullable=True),
        sa.Column("external_menu_name", sa.String(length=255), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=True),
        sa.Column("raw_menu", sa.JSON(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id"),
    )

    op.create_table(
        "menu_item_contents",
        sa.Column("iiko_item_id", sa.String(length=64), nullable=True),
        sa.Column("sku", sa.String(length=64), nullable=True),
        sa.Column("name_override", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("image_url", sa.String(length=1024), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_menu_item_contents_active_sort", "menu_item_contents", ["is_active", "sort_order"], unique=False)
    op.create_index(
        "uq_menu_item_contents_iiko_item_id",
        "menu_item_contents",
        ["iiko_item_id"],
        unique=True,
        postgresql_where=sa.text("iiko_item_id IS NOT NULL"),
    )
    op.create_index(
        "uq_menu_item_contents_sku",
        "menu_item_contents",
        ["sku"],
        unique=True,
        postgresql_where=sa.text("sku IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_menu_item_contents_sku", table_name="menu_item_contents")
    op.drop_index("uq_menu_item_contents_iiko_item_id", table_name="menu_item_contents")
    op.drop_index("ix_menu_item_contents_active_sort", table_name="menu_item_contents")
    op.drop_table("menu_item_contents")
    op.drop_table("iiko_menu_snapshots")

    op.drop_index("ix_organizations_default_delivery", table_name="organizations")
    op.drop_index(op.f("ix_organizations_iiko_organization_id"), table_name="organizations")
    op.drop_column("organizations", "is_default_delivery")
    op.drop_column("organizations", "accepts_delivery")
    op.drop_column("organizations", "accepts_pickup")
    op.drop_column("organizations", "iiko_organization_id")

    op.drop_index(op.f("ix_organizations_iiko_api_login"), table_name="organizations")
    op.create_index(op.f("ix_organizations_iiko_api_login"), "organizations", ["iiko_api_login"], unique=True)
