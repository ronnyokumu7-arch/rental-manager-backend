"""add investor lease fields to vehicles

Revision ID: 89fc0e855165
Revises: 4f5b34cb3350
Create Date: 2026-09-27 18:01:00.017509

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '89fc0e855165'
down_revision: Union[str, Sequence[str], None] = '4f5b34cb3350'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('vehicles', sa.Column('investor_lease_rate', sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column('vehicles', sa.Column('lease_rate_type', sa.String(length=20), nullable=True, server_default='daily'))
    op.add_column('vehicles', sa.Column('lease_rate_locked', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('vehicles', 'lease_rate_locked')
    op.drop_column('vehicles', 'lease_rate_type')
    op.drop_column('vehicles', 'investor_lease_rate')
