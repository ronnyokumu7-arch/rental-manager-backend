"""add_pay_as_you_go_to_plan_type_and_billing_cycle

Revision ID: c2670f079fcb
Revises: 63be7ab9060e
Create Date: 2026-07-11 23:25:14.221521

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2670f079fcb'
down_revision: Union[str, Sequence[str], None] = '63be7ab9060e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE plantype ADD VALUE IF NOT EXISTS 'pay_as_you_go'")
    op.execute("ALTER TYPE billingcycle ADD VALUE IF NOT EXISTS 'pay_as_you_go'")


def downgrade() -> None:
    """Downgrade schema."""
    pass
