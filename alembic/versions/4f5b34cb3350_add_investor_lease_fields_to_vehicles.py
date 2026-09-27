"""add investor lease fields to vehicles

Revision ID: 4f5b34cb3350
Revises: a91d2c7e4f60
Create Date: 2026-09-27 15:29:00.688217

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4f5b34cb3350'
down_revision: Union[str, Sequence[str], None] = 'a91d2c7e4f60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ✅ Add the 3 new columns for investor lease agreements
    op.add_column('vehicles', sa.Column('investor_lease_rate', sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column('vehicles', sa.Column('lease_rate_type', sa.String(length=20), nullable=True, server_default='daily'))
    op.add_column('vehicles', sa.Column('lease_rate_locked', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    """Downgrade schema."""
    # ✅ Safely remove them if we ever need to roll back
    op.drop_column('vehicles', 'lease_rate_locked')
    op.drop_column('vehicles', 'lease_rate_type')
    op.drop_column('vehicles', 'investor_lease_rate')
