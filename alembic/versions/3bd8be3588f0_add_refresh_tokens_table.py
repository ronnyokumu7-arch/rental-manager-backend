"""add_refresh_tokens_table

Revision ID: 3bd8be3588f0
Revises: b20d74462350
Create Date: 2026-07-31 22:31:31.810746

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3bd8be3588f0'
down_revision: Union[str, Sequence[str], None] = 'b20d74462350'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    
    # =========================================================================
    # ✅ CREATE REFRESH TOKENS TABLE (the actual intent of this migration)
    # =========================================================================
    op.create_table(
        'refresh_tokens',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('token_hash', sa.String(255), unique=True, index=True, nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column('revoked', sa.Boolean(), nullable=False, server_default='false', index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    )
    
    # Composite indexes for efficient validation and cleanup
    op.create_index('ix_refresh_tokens_validation', 'refresh_tokens', ['token_hash', 'revoked', 'expires_at'])
    op.create_index('ix_refresh_tokens_expires', 'refresh_tokens', ['expires_at'])
    op.create_index('ix_refresh_tokens_user', 'refresh_tokens', ['user_id', 'revoked'])
    
    # =========================================================================
    # ✅ INDEX REORGANIZATIONS (from earlier model updates - safe to keep)
    # =========================================================================
    
    # Contracts: composite (tenant_id, id) → single tenant_id index
    op.drop_index(op.f('ix_contracts_tenant_id'), table_name='contracts')
    op.create_index(op.f('ix_contracts_tenant_id'), 'contracts', ['tenant_id'], unique=False)
    
    # Invoices: single tenant_id index → composite (tenant_id, id) index
    op.drop_index(op.f('ix_invoices_tenant_id'), table_name='invoices')
    op.create_index('ix_invoices_tenant_id', 'invoices', ['tenant_id', 'id'], unique=False)
    
    # Payments: composite (tenant_id, id) → single tenant_id index
    op.drop_index(op.f('ix_payments_tenant_id'), table_name='payments')
    op.create_index(op.f('ix_payments_tenant_id'), 'payments', ['tenant_id'], unique=False)
    
    # Subscriptions: composite (tenant_id, id) → single tenant_id index
    op.drop_index(op.f('ix_subscriptions_tenant_id'), table_name='subscriptions')
    op.create_index(op.f('ix_subscriptions_tenant_id'), 'subscriptions', ['tenant_id'], unique=False)
    
    # Vehicles: composite (tenant_id, id) → single tenant_id index
    op.drop_index(op.f('ix_vehicles_tenant_id'), table_name='vehicles')
    op.create_index(op.f('ix_vehicles_tenant_id'), 'vehicles', ['tenant_id'], unique=False)
    
    # =========================================================================
    # 🚫 REMOVED: All drop_table commands for payment gateway tables
    # These tables contain encrypted tenant credentials and must NOT be dropped.
    # =========================================================================


def downgrade() -> None:
    """Downgrade schema."""
    
    # =========================================================================
    # ✅ REVERT REFRESH TOKENS TABLE
    # =========================================================================
    op.drop_index('ix_refresh_tokens_user', table_name='refresh_tokens')
    op.drop_index('ix_refresh_tokens_expires', table_name='refresh_tokens')
    op.drop_index('ix_refresh_tokens_validation', table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
    
    # =========================================================================
    # ✅ REVERT INDEX REORGANIZATIONS
    # =========================================================================
    op.drop_index(op.f('ix_vehicles_tenant_id'), table_name='vehicles')
    op.create_index(op.f('ix_vehicles_tenant_id'), 'vehicles', ['tenant_id', 'id'], unique=False)
    
    op.drop_index(op.f('ix_subscriptions_tenant_id'), table_name='subscriptions')
    op.create_index(op.f('ix_subscriptions_tenant_id'), 'subscriptions', ['tenant_id', 'id'], unique=False)
    
    op.drop_index(op.f('ix_payments_tenant_id'), table_name='payments')
    op.create_index(op.f('ix_payments_tenant_id'), 'payments', ['tenant_id', 'id'], unique=False)
    
    op.drop_index('ix_invoices_tenant_id', table_name='invoices')
    op.create_index(op.f('ix_invoices_tenant_id'), 'invoices', ['tenant_id'], unique=False)
    
    op.drop_index(op.f('ix_contracts_tenant_id'), table_name='contracts')
    op.create_index(op.f('ix_contracts_tenant_id'), 'contracts', ['tenant_id', 'id'], unique=False)
    
    # =========================================================================
    # 🚫 REMOVED: All create_table commands for payment gateway tables
    # These tables already exist in the database.
    # =========================================================================
