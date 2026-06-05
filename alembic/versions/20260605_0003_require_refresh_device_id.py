"""require refresh session device id

Revision ID: 20260605_0003
Revises: 20260519_0002
Create Date: 2026-06-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260605_0003"
down_revision: Union[str, Sequence[str], None] = "20260519_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE refresh_sessions
        SET revoked_at = COALESCE(revoked_at, NOW())
        WHERE device_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE refresh_sessions
        SET device_id = 'legacy-revoked-' || id::text
        WHERE device_id IS NULL
        """
    )
    op.alter_column("refresh_sessions", "device_id", existing_type=sa.String(length=128), nullable=False)


def downgrade() -> None:
    op.alter_column("refresh_sessions", "device_id", existing_type=sa.String(length=128), nullable=True)
