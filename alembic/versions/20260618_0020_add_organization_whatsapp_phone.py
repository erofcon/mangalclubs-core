"""add organization whatsapp phone

Revision ID: 20260618_0020
Revises: 20260617_0019
Create Date: 2026-06-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260618_0020"
down_revision: Union[str, Sequence[str], None] = "20260617_0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("whatsapp_phone", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("organizations", "whatsapp_phone")
