"""ensure booking category preview url exists

Some databases were created or upgraded from an older booking-category
schema where this column was missing, while the ORM model already expects it.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260810_0024"
down_revision: Union[str, Sequence[str], None] = "20260730_0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("booking_categories")}
    if "preview_url" not in columns:
        op.add_column(
            "booking_categories",
            sa.Column("preview_url", sa.String(length=1024), nullable=True),
        )


def downgrade() -> None:
    # This is a repair migration. Do not remove a column that may have existed
    # before the repair migration was applied.
    pass
