"""rename_is_super_tenant_admin_to_is_tenant_owner_and_add_constraints

Revision ID: b20d74462350
Revises: d7c7fb8fe084
Create Date: 2026-07-31 21:35:36.835073

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b20d74462350'
down_revision: Union[str, Sequence[str], None] = 'd7c7fb8fe084'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    
    # =========================================================================
    # ✅ USER MODEL CHANGES (the actual intent of this migration)
    # =========================================================================
    
    # 1. Add new is_tenant_owner column (replaces is_super_tenant_admin)
    op.add_column('users', sa.Column('is_tenant_owner', sa.Boolean(), server_default='false', nullable=False))
    
    # 2. Drop the old is_super_tenant_admin column
    op.drop_column('users', 'is_super_tenant_admin')
    
    # 3. Add CheckConstraint to prevent negative failed_login_attempts
    op.create_check_constraint(
        'ck_users_failed_login_attempts_non_negative',
        'users',
        'failed_login_attempts >= 0'
    )
    
    # =========================================================================
    # ✅ INDEX REORGANIZATIONS (from earlier model updates - safe to keep)
    # =========================================================================
    
    # Contracts: single tenant_id index → composite (tenant_id, id) index
    op.drop_index(op.f('ix_contracts_tenant_id'), table_name='contracts')
    op.create_index('ix_contracts_tenant_id', 'contracts', ['tenant_id', 'id'], unique=False)
    
    # Invoices: composite (tenant_id, id) → single tenant_id index
    op.drop_index(op.f('ix_invoices_tenant_id'), table_name='invoices')
    op.create_index(op.f('ix_invoices_tenant_id'), 'invoices', ['tenant_id'], unique=False)
    
    # Payments: single tenant_id index → composite (tenant_id, id) index
    op.drop_index(op.f('ix_payments_tenant_id'), table_name='payments')
    op.create_index('ix_payments_tenant_id', 'payments', ['tenant_id', 'id'], unique=False)
    
    # Subscriptions: single tenant_id index → composite (tenant_id, id) index
    op.drop_index(op.f('ix_subscriptions_tenant_id'), table_name='subscriptions')
    op.create_index('ix_subscriptions_tenant_id', 'subscriptions', ['tenant_id', 'id'], unique=False)
    
    # Vehicles: single tenant_id index → composite (tenant_id, id) index
    op.drop_index(op.f('ix_vehicles_tenant_id'), table_name='vehicles')
    op.create_index('ix_vehicles_tenant_id', 'vehicles', ['tenant_id', 'id'], unique=False)
    
    # =========================================================================
    # 🚫 REMOVED: All drop_table commands for payment gateway tables
    # These tables still exist and contain encrypted tenant credentials.
    # Dropping them would cause catastrophic data loss.
    # =========================================================================


def downgrade() -> None:
    """Downgrade schema."""
    
    # =========================================================================
    # ✅ REVERT INDEX REORGANIZATIONS
    # =========================================================================
    op.drop_index('ix_vehicles_tenant_id', table_name='vehicles')
    op.create_index(op.f('ix_vehicles_tenant_id'), 'vehicles', ['tenant_id'], unique=False)
    
    op.drop_index('ix_subscriptions_tenant_id', table_name='subscriptions')
    op.create_index(op.f('ix_subscriptions_tenant_id'), 'subscriptions', ['tenant_id'], unique=False)
    
    op.drop_index('ix_payments_tenant_id', table_name='payments')
    op.create_index(op.f('ix_payments_tenant_id'), 'payments', ['tenant_id'], unique=False)
    
    op.drop_index(op.f('ix_invoices_tenant_id'), table_name='invoices')
    op.create_index(op.f('ix_invoices_tenant_id'), 'invoices', ['tenant_id', 'id'], unique=False)
    
    op.drop_index('ix_contracts_tenant_id', table_name='contracts')
    op.create_index(op.f('ix_contracts_tenant_id'), 'contracts', ['tenant_id'], unique=False)
    
    # =========================================================================
    # ✅ REVERT USER MODEL CHANGES
    # =========================================================================
    
    # 1. Drop the CheckConstraint
    op.drop_constraint('ck_users_failed_login_attempts_non_negative', 'users', type_='check')
    
    # 2. Restore the old is_super_tenant_admin column
    op.add_column('users', sa.Column('is_super_tenant_admin', sa.Boolean(), server_default='false', nullable=False))
    
    # 3. Drop the new is_tenant_owner column
    op.drop_column('users', 'is_tenant_owner')
    
    # =========================================================================
    # 🚫 REMOVED: All create_table commands for payment gateway tables
    # These tables already exist in the database. Recreating them would fail.
    # =========================================================================
