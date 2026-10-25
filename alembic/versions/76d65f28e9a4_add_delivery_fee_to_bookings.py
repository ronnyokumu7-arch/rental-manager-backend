"""add_delivery_fee_to_bookings

Revision ID: 76d65f28e9a4
Revises: 1381e9cd5f7d
Create Date: 2026-10-25 22:31:04.737231

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '76d65f28e9a4'
down_revision: Union[str, Sequence[str], None] = '1381e9cd5f7d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'bookings',
        sa.Column('delivery_fee', sa.Numeric(precision=10, scale=2), server_default='0', nullable=False)
    )
    op.create_check_constraint(
        'ck_bookings_delivery_fee_non_negative',
        'bookings',
        'delivery_fee >= 0'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_bookings_delivery_fee_non_negative', 'bookings', type_='check')
    op.drop_column('bookings', 'delivery_fee')
