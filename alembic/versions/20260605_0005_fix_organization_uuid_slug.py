"""fix organization uuid slug

Revision ID: 20260605_0005
Revises: 20260605_0004
Create Date: 2026-06-05

"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "20260605_0005"
down_revision: Union[str, Sequence[str], None] = "20260605_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "organizations" not in table_names:
        return

    organization_columns = {column["name"]: column for column in inspector.get_columns("organizations")}
    id_type = str(organization_columns["id"]["type"]).lower()

    if "slug" in organization_columns and "uuid" in id_type:
        bind.execute(sa.text("CREATE UNIQUE INDEX IF NOT EXISTS ix_organizations_slug ON organizations (slug)"))
        return

    if "slug" in organization_columns:
        return

    bind.execute(
        sa.text("ALTER TABLE organization_working_hours DROP CONSTRAINT IF EXISTS organization_working_hours_organization_id_fkey")
    )
    bind.execute(sa.text("ALTER TABLE organization_working_hours DROP CONSTRAINT IF EXISTS uq_organization_working_hours_weekday"))
    bind.execute(sa.text("ALTER TABLE organizations DROP CONSTRAINT IF EXISTS organizations_pkey"))

    op.alter_column(
        "organization_working_hours",
        "organization_id",
        new_column_name="organization_slug",
        existing_type=sa.String(length=64),
        existing_nullable=False,
    )
    op.alter_column(
        "organizations",
        "id",
        new_column_name="slug",
        existing_type=sa.String(length=64),
        existing_nullable=False,
    )

    op.add_column("organizations", sa.Column("id", sa.UUID(), nullable=True))
    rows = bind.execute(sa.text("SELECT slug FROM organizations")).fetchall()
    for row in rows:
        bind.execute(
            sa.text("UPDATE organizations SET id = :id WHERE slug = :slug"),
            {"id": uuid.uuid4(), "slug": row.slug},
        )

    op.alter_column("organizations", "id", existing_type=sa.UUID(), nullable=False)
    op.create_primary_key("organizations_pkey", "organizations", ["id"])
    bind.execute(sa.text("CREATE UNIQUE INDEX IF NOT EXISTS ix_organizations_slug ON organizations (slug)"))

    op.add_column("organization_working_hours", sa.Column("organization_id", sa.UUID(), nullable=True))
    bind.execute(
        sa.text(
            """
            UPDATE organization_working_hours AS hours
            SET organization_id = organizations.id
            FROM organizations
            WHERE hours.organization_slug = organizations.slug
            """
        )
    )
    op.alter_column("organization_working_hours", "organization_id", existing_type=sa.UUID(), nullable=False)
    op.create_unique_constraint(
        "uq_organization_working_hours_weekday",
        "organization_working_hours",
        ["organization_id", "weekday"],
    )
    op.create_foreign_key(
        "organization_working_hours_organization_id_fkey",
        "organization_working_hours",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_column("organization_working_hours", "organization_slug")


def downgrade() -> None:
    pass
