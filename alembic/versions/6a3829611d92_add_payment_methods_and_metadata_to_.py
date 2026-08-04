"""add_payment_methods_and_metadata_to_tenants

Revision ID: 6a3829611d92
Revises: c2670f079fcb
Create Date: 2026-07-11 23:45:12.956942

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '6a3829611d92'
down_revision: Union[str, Sequence[str], None] = 'c2670f079fcb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Define the enum object once so it can be cleanly referenced
payment_method_enum = postgresql.ENUM('mpesa', 'card', 'paypal', 'bank', name='paymentmethodtype')


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Safely create the enum type if it doesn't already exist
    payment_method_enum.create(op.get_bind(), checkfirst=True)

    # 2. Add columns and indexes
    op.add_column('tenants', sa.Column('default_payment_method', payment_method_enum, nullable=True))
    op.add_column('tenants', sa.Column('stripe_customer_id', sa.String(), nullable=True))
    op.add_column('tenants', sa.Column('paypal_payer_id', sa.String(), nullable=True))
    op.add_column('tenants', sa.Column('payment_metadata', sa.JSON(), nullable=True))
    op.create_index(op.f('ix_tenants_stripe_customer_id'), 'tenants', ['stripe_customer_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # 1. Drop index and columns
    op.drop_index(op.f('ix_tenants_stripe_customer_id'), table_name='tenants')
    op.drop_column('tenants', 'payment_metadata')
    op.drop_column('tenants', 'paypal_payer_id')
    op.drop_column('tenants', 'stripe_customer_id')
    op.drop_column('tenants', 'default_payment_method')

    # 2. Cleanly drop the enum type
    payment_method_enum.drop(op.get_bind(), checkfirst=True)
