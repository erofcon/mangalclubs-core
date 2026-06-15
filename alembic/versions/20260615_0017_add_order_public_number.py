"""add order public number

Revision ID: 20260615_0017
Revises: 20260614_0016
Create Date: 2026-06-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260615_0017"
down_revision: Union[str, Sequence[str], None] = "20260614_0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("CREATE SEQUENCE order_public_number_seq START WITH 1 INCREMENT BY 1"))
    op.add_column("orders", sa.Column("public_number", sa.String(length=32), nullable=True))
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION encode_order_public_number(value bigint)
            RETURNS text AS $$
            DECLARE
                alphabet text := '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
                base integer := length(alphabet);
                encoded text := '';
                remainder integer;
            BEGIN
                IF value < 1 THEN
                    RAISE EXCEPTION 'Public order number value must be positive';
                END IF;

                WHILE value > 0 LOOP
                    remainder := value % base;
                    encoded := substr(alphabet, remainder + 1, 1) || encoded;
                    value := value / base;
                END LOOP;

                RETURN lpad(encoded, 6, '0');
            END;
            $$ LANGUAGE plpgsql IMMUTABLE;
            """
        )
    )
    op.execute(
        sa.text(
            """
            WITH numbered AS (
                SELECT id, row_number() OVER (ORDER BY created_at, id) AS seq
                FROM orders
            )
            UPDATE orders
            SET public_number = encode_order_public_number(numbered.seq)
            FROM numbered
            WHERE orders.id = numbered.id
            """
        )
    )
    op.execute(
        sa.text(
            """
            SELECT setval(
                'order_public_number_seq',
                GREATEST((SELECT count(*) FROM orders), 1),
                (SELECT count(*) FROM orders) > 0
            )
            """
        )
    )
    op.alter_column("orders", "public_number", nullable=False)
    op.create_index("ix_orders_public_number", "orders", ["public_number"], unique=True)
    op.execute(sa.text("DROP FUNCTION encode_order_public_number(bigint)"))


def downgrade() -> None:
    op.drop_index("ix_orders_public_number", table_name="orders")
    op.drop_column("orders", "public_number")
    op.execute(sa.text("DROP SEQUENCE order_public_number_seq"))
