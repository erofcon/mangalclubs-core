"""repair delivery zone compatibility columns

Some deployed databases contain ``sort_order`` and ``is_active`` columns on
``delivery_zones`` even though the original migration in this repository did
not create them. They are NOT NULL, so inserts from the ORM failed because
the model did not know about the columns.

The repair is additive and preserves any existing values. It also makes the
defaults available to direct SQL inserts and to fresh installations.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260812_0025"
down_revision: Union[str, Sequence[str], None] = "20260810_0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("delivery_zones")}

    if "sort_order" not in columns:
        op.add_column("delivery_zones", sa.Column("sort_order", sa.Integer(), nullable=True))
    if "is_active" not in columns:
        op.add_column("delivery_zones", sa.Column("is_active", sa.Boolean(), nullable=True))

    # Preserve existing values and make the columns safe for all future
    # inserts, including inserts that do not go through SQLAlchemy ORM.
    op.execute(sa.text("UPDATE delivery_zones SET sort_order = 0 WHERE sort_order IS NULL"))
    op.execute(sa.text("UPDATE delivery_zones SET is_active = TRUE WHERE is_active IS NULL"))

    op.alter_column(
        "delivery_zones",
        "sort_order",
        existing_type=sa.Integer(),
        nullable=False,
        server_default=sa.text("0"),
    )
    op.alter_column(
        "delivery_zones",
        "is_active",
        existing_type=sa.Boolean(),
        nullable=False,
        server_default=sa.text("true"),
    )


def downgrade() -> None:
    # This is a compatibility repair. The columns may have existed before
    # this migration, so removing them could destroy deployed data.
    pass
