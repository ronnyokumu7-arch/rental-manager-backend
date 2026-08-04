"""add discount fields to invoices

Revision ID: 87ab49d35d6b
Revises: a906bd02fd46
Create Date: 2026-07-17 01:08:56.707951

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '87ab49d35d6b'
down_revision: Union[str, Sequence[str], None] = 'a906bd02fd46'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('invoices', sa.Column('discount_amount', sa.Numeric(precision=12, scale=2), nullable=True))
    op.execute("UPDATE invoices SET discount_amount = 0 WHERE discount_amount IS NULL")
    op.alter_column('invoices', 'discount_amount', nullable=False)
    op.add_column('invoices', sa.Column('discount_reason', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('invoices', 'discount_reason')
    op.drop_column('invoices', 'discount_amount')
