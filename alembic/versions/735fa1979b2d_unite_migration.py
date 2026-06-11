"""unite migration

Revision ID: 735fa1979b2d
Revises: 20260608_0009, 20260609_0011
Create Date: 2026-06-10 09:21:55.491727

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '735fa1979b2d'
down_revision: Union[str, Sequence[str], None] = ('20260608_0009', '20260609_0011')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
