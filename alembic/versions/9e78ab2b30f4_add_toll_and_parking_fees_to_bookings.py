"""add_toll_and_parking_fees_to_bookings

Revision ID: 9e78ab2b30f4
Revises: 935aa301750d
Create Date: 2026-08-31 13:16:36.658371

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9e78ab2b30f4'
down_revision: Union[str, Sequence[str], None] = '935aa301750d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add toll_fees column
    op.add_column('bookings', sa.Column('toll_fees', sa.Numeric(precision=10, scale=2), nullable=False, server_default='0'))
    
    # Add parking_fees column
    op.add_column('bookings', sa.Column('parking_fees', sa.Numeric(precision=10, scale=2), nullable=False, server_default='0'))
    
    # Add check constraints
    op.create_check_constraint(
        'ck_bookings_toll_fees_non_negative',
        'bookings',
        'toll_fees >= 0'
    )
    op.create_check_constraint(
        'ck_bookings_parking_fees_non_negative',
        'bookings',
        'parking_fees >= 0'
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Drop check constraints first
    op.drop_constraint('ck_bookings_parking_fees_non_negative', 'bookings', type_='check')
    op.drop_constraint('ck_bookings_toll_fees_non_negative', 'bookings', type_='check')
    
    # Drop columns
    op.drop_column('bookings', 'parking_fees')
    op.drop_column('bookings', 'toll_fees')
