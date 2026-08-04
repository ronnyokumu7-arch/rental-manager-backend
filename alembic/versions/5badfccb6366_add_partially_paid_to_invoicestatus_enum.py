"""add partially_paid to invoicestatus enum

Revision ID: 5badfccb6366
Revises: 2cfc8350a8c1
Create Date: 2026-07-17 03:05:31.537386

"""
from typing import Sequence, Union

from alembic import op

revision: str = '5badfccb6366'
down_revision: Union[str, Sequence[str], None] = '2cfc8350a8c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add the new value to the existing PostgreSQL enum type
    op.execute("ALTER TYPE invoicestatus ADD VALUE IF NOT EXISTS 'partially_paid'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values easily.
    # This is a safe no-op for downgrades, which is standard practice.
    pass
