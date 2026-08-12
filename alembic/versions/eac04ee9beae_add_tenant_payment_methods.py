"""add_tenant_payment_methods

Revision ID: eac04ee9beae
Revises: 75eadb58e196
Create Date: 2026-08-12 18:10:15.763934

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eac04ee9beae'
down_revision: Union[str, Sequence[str], None] = '75eadb58e196'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ✅ NEW: Tenant payment methods (M-Pesa, Airtel Money & Bank).
    # All nullable → zero-downtime, no data migration needed.
    op.add_column('tenant_profiles', sa.Column('mpesa_paybill', sa.String(length=10), nullable=True))
    op.add_column('tenant_profiles', sa.Column('mpesa_paybill_account', sa.String(length=50), nullable=True))
    op.add_column('tenant_profiles', sa.Column('mpesa_till', sa.String(length=10), nullable=True))
    op.add_column('tenant_profiles', sa.Column('mpesa_pochi', sa.String(length=10), nullable=True))
    op.add_column('tenant_profiles', sa.Column('mpesa_number', sa.String(length=20), nullable=True))
    op.add_column('tenant_profiles', sa.Column('airtel_number', sa.String(length=20), nullable=True))
    op.add_column('tenant_profiles', sa.Column('bank_name', sa.String(length=100), nullable=True))
    op.add_column('tenant_profiles', sa.Column('bank_account', sa.String(length=34), nullable=True))
    op.add_column('tenant_profiles', sa.Column('bank_account_name', sa.String(length=150), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('tenant_profiles', 'bank_account_name')
    op.drop_column('tenant_profiles', 'bank_account')
    op.drop_column('tenant_profiles', 'bank_name')
    op.drop_column('tenant_profiles', 'airtel_number')
    op.drop_column('tenant_profiles', 'mpesa_number')
    op.drop_column('tenant_profiles', 'mpesa_pochi')
    op.drop_column('tenant_profiles', 'mpesa_till')
    op.drop_column('tenant_profiles', 'mpesa_paybill_account')
    op.drop_column('tenant_profiles', 'mpesa_paybill')
