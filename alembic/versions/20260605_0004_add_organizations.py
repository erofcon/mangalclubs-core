"""add organizations

Revision ID: 20260605_0004
Revises: 20260605_0003
Create Date: 2026-06-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260605_0004"
down_revision: Union[str, Sequence[str], None] = "20260605_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("city", sa.String(length=255), nullable=False),
        sa.Column("address", sa.String(length=500), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("intro", sa.Text(), nullable=False),
        sa.Column("latitude", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("longitude", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("photo_url", sa.String(length=1024), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("latitude >= -90 AND latitude <= 90", name="ck_organizations_latitude_range"),
        sa.CheckConstraint("longitude >= -180 AND longitude <= 180", name="ck_organizations_longitude_range"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_organizations_city"), "organizations", ["city"], unique=False)
    op.create_index(op.f("ix_organizations_slug"), "organizations", ["slug"], unique=True)

    op.create_table(
        "organization_working_hours",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("is_closed", sa.Boolean(), nullable=False),
        sa.Column("opens_at", sa.Time(timezone=False), nullable=True),
        sa.Column("closes_at", sa.Time(timezone=False), nullable=True),
        sa.CheckConstraint(
            "weekday >= 0 AND weekday <= 6",
            name="ck_organization_working_hours_weekday_range",
        ),
        sa.CheckConstraint(
            "(is_closed = true AND opens_at IS NULL AND closes_at IS NULL) "
            "OR (is_closed = false AND opens_at IS NOT NULL AND closes_at IS NOT NULL)",
            name="ck_organization_working_hours_time_presence",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "weekday", name="uq_organization_working_hours_weekday"),
    )


def downgrade() -> None:
    op.drop_table("organization_working_hours")
    op.drop_index(op.f("ix_organizations_slug"), table_name="organizations")
    op.drop_index(op.f("ix_organizations_city"), table_name="organizations")
    op.drop_table("organizations")
