"""production_hardening_2026_08

Revision ID: 92a70c75d07b
Revises: 3bd8be3588f0
Create Date: 2026-08-01 17:43:49.883434

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '92a70c75d07b'
down_revision: Union[str, Sequence[str], None] = '3bd8be3588f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # =========================================================================
    # ACTIVITY LOGS — Add tenant_id with safe backfill
    # =========================================================================
    op.add_column('activity_logs', sa.Column('tenant_id', sa.Integer(), nullable=True))
    
    op.execute("""
        UPDATE activity_logs
        SET tenant_id = users.tenant_id
        FROM users
        WHERE activity_logs.user_id = users.id
    """)
    
    op.alter_column('activity_logs', 'tenant_id', nullable=False)
    op.alter_column('activity_logs', 'user_id', existing_type=sa.INTEGER(), nullable=True)
    op.drop_constraint(op.f('activity_logs_user_id_fkey'), 'activity_logs', type_='foreignkey')
    op.create_foreign_key('fk_activity_logs_user_id', 'activity_logs', 'users', ['user_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_activity_logs_tenant_id', 'activity_logs', 'tenants', ['tenant_id'], ['id'], ondelete='CASCADE')
    
    op.drop_index(op.f('ix_activity_logs_user_created'), table_name='activity_logs')
    op.create_index('ix_activity_logs_target', 'activity_logs', ['tenant_id', 'target_type', 'target_id', 'created_at'], unique=False)
    op.create_index('ix_activity_logs_tenant_action', 'activity_logs', ['tenant_id', 'action', 'created_at'], unique=False)
    op.create_index('ix_activity_logs_tenant_created', 'activity_logs', ['tenant_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_activity_logs_tenant_id'), 'activity_logs', ['tenant_id'], unique=False)
    op.create_index('ix_activity_logs_tenant_user_created', 'activity_logs', ['tenant_id', 'user_id', 'created_at'], unique=False)

    # =========================================================================
    # REFRESH TOKENS — Add tenant_id with safe backfill
    # =========================================================================
    op.add_column('refresh_tokens', sa.Column('tenant_id', sa.Integer(), nullable=True))
    
    op.execute("""
        UPDATE refresh_tokens
        SET tenant_id = users.tenant_id
        FROM users
        WHERE refresh_tokens.user_id = users.id
    """)
    
    op.alter_column('refresh_tokens', 'tenant_id', nullable=False)
    op.add_column('refresh_tokens', sa.Column('user_agent', sa.String(length=500), nullable=True))
    op.add_column('refresh_tokens', sa.Column('ip_address', sa.String(length=45), nullable=True))
    op.create_foreign_key('fk_refresh_tokens_tenant_id', 'refresh_tokens', 'tenants', ['tenant_id'], ['id'], ondelete='CASCADE')
    
    op.create_index(op.f('ix_refresh_tokens_id'), 'refresh_tokens', ['id'], unique=False)
    op.create_index('ix_refresh_tokens_tenant_active', 'refresh_tokens', ['tenant_id', 'revoked', 'expires_at'], unique=False)
    op.create_index(op.f('ix_refresh_tokens_tenant_id'), 'refresh_tokens', ['tenant_id'], unique=False)
    op.create_index('ix_refresh_tokens_user_active', 'refresh_tokens', ['user_id', 'revoked', 'expires_at', 'created_at'], unique=False)

    # =========================================================================
    # PAYMENT GATEWAY CONFIGS — Replace unique constraints with unique indexes
    # =========================================================================
    op.drop_constraint(op.f('airtel_money_configs_tenant_id_key'), 'airtel_money_configs', type_='unique')
    op.create_index(op.f('ix_airtel_money_configs_tenant_id'), 'airtel_money_configs', ['tenant_id'], unique=True)
    
    op.drop_constraint(op.f('mpesa_configs_tenant_id_key'), 'mpesa_configs', type_='unique')
    op.create_index(op.f('ix_mpesa_configs_tenant_id'), 'mpesa_configs', ['tenant_id'], unique=True)
    
    op.drop_constraint(op.f('paypal_configs_tenant_id_key'), 'paypal_configs', type_='unique')
    op.create_index(op.f('ix_paypal_configs_tenant_id'), 'paypal_configs', ['tenant_id'], unique=True)
    
    op.drop_constraint(op.f('stripe_configs_tenant_id_key'), 'stripe_configs', type_='unique')
    op.create_index(op.f('ix_stripe_configs_tenant_id'), 'stripe_configs', ['tenant_id'], unique=True)

    # =========================================================================
    # BANK ACCOUNT CONFIGS — Widen account_number
    # =========================================================================
    op.alter_column('bank_account_configs', 'account_number',
               existing_type=sa.VARCHAR(length=50),
               type_=sa.String(length=255),
               existing_nullable=False)

    # =========================================================================
    # CONTRACTS — Tenant-scoped unique contract_number
    # =========================================================================
    op.drop_constraint(op.f('contracts_contract_number_key'), 'contracts', type_='unique')
    op.drop_index(op.f('ix_contracts_tenant_id'), table_name='contracts')
    op.create_index('ix_contracts_tenant_id', 'contracts', ['tenant_id', 'id'], unique=False)
    op.create_unique_constraint('uq_tenant_contract_number', 'contracts', ['tenant_id', 'contract_number'])

    # =========================================================================
    # INVOICES — Tenant-scoped unique invoice_number
    # =========================================================================
    op.drop_index(op.f('ix_invoices_invoice_number'), table_name='invoices')
    op.create_index(op.f('ix_invoices_invoice_number'), 'invoices', ['invoice_number'], unique=False)
    op.drop_index(op.f('ix_invoices_tenant_id'), table_name='invoices')
    op.create_index(op.f('ix_invoices_tenant_id'), 'invoices', ['tenant_id'], unique=False)
    op.create_unique_constraint('uq_tenant_invoice_number', 'invoices', ['tenant_id', 'invoice_number'])

    # =========================================================================
    # ROLE TEMPLATES — Add description, tenant-scoped unique job_title
    # =========================================================================
    op.add_column('role_templates', sa.Column('description', sa.String(length=500), nullable=True))
    
    # ✅ FIX: Deduplicate job_titles to prevent UniqueViolation.
    # Renames duplicates to "Job Title (Duplicate ID)" to preserve data safely.
    op.execute("""
        UPDATE role_templates
        SET job_title = job_title || ' (Duplicate ' || id || ')'
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM role_templates
            GROUP BY tenant_id, job_title
        )
    """)
    
    op.drop_index(op.f('ix_role_templates_tenant_id'), table_name='role_templates')
    op.create_index('ix_role_templates_tenant_id', 'role_templates', ['tenant_id', 'id'], unique=False)
    op.create_unique_constraint('uq_tenant_role_template_job_title', 'role_templates', ['tenant_id', 'job_title'])


def downgrade() -> None:
    op.drop_constraint('uq_tenant_role_template_job_title', 'role_templates', type_='unique')
    op.drop_index('ix_role_templates_tenant_id', table_name='role_templates')
    op.create_index(op.f('ix_role_templates_tenant_id'), 'role_templates', ['tenant_id'], unique=False)
    op.drop_column('role_templates', 'description')
    
    op.drop_constraint('uq_tenant_invoice_number', 'invoices', type_='unique')
    op.drop_index(op.f('ix_invoices_tenant_id'), table_name='invoices')
    op.create_index(op.f('ix_invoices_tenant_id'), 'invoices', ['tenant_id', 'id'], unique=False)
    op.drop_index(op.f('ix_invoices_invoice_number'), table_name='invoices')
    op.create_index(op.f('ix_invoices_invoice_number'), 'invoices', ['invoice_number'], unique=True)
    
    op.drop_constraint('uq_tenant_contract_number', 'contracts', type_='unique')
    op.drop_index('ix_contracts_tenant_id', table_name='contracts')
    op.create_index(op.f('ix_contracts_tenant_id'), 'contracts', ['tenant_id'], unique=False)
    op.create_unique_constraint(op.f('contracts_contract_number_key'), 'contracts', ['contract_number'])
    
    op.alter_column('bank_account_configs', 'account_number',
               existing_type=sa.String(length=255),
               type_=sa.VARCHAR(length=50),
               existing_nullable=False)
    
    op.drop_index(op.f('ix_stripe_configs_tenant_id'), table_name='stripe_configs')
    op.create_unique_constraint(op.f('stripe_configs_tenant_id_key'), 'stripe_configs', ['tenant_id'])
    op.drop_index(op.f('ix_paypal_configs_tenant_id'), table_name='paypal_configs')
    op.create_unique_constraint(op.f('paypal_configs_tenant_id_key'), 'paypal_configs', ['tenant_id'])
    op.drop_index(op.f('ix_mpesa_configs_tenant_id'), table_name='mpesa_configs')
    op.create_unique_constraint(op.f('mpesa_configs_tenant_id_key'), 'mpesa_configs', ['tenant_id'])
    op.drop_index(op.f('ix_airtel_money_configs_tenant_id'), table_name='airtel_money_configs')
    op.create_unique_constraint(op.f('airtel_money_configs_tenant_id_key'), 'airtel_money_configs', ['tenant_id'])
    
    op.drop_constraint('fk_refresh_tokens_tenant_id', 'refresh_tokens', type_='foreignkey')
    op.drop_index('ix_refresh_tokens_user_active', table_name='refresh_tokens')
    op.drop_index(op.f('ix_refresh_tokens_tenant_id'), table_name='refresh_tokens')
    op.drop_index('ix_refresh_tokens_tenant_active', table_name='refresh_tokens')
    op.drop_index(op.f('ix_refresh_tokens_id'), table_name='refresh_tokens')
    op.drop_column('refresh_tokens', 'ip_address')
    op.drop_column('refresh_tokens', 'user_agent')
    op.drop_column('refresh_tokens', 'tenant_id')
    
    op.drop_constraint('fk_activity_logs_tenant_id', 'activity_logs', type_='foreignkey')
    op.drop_constraint('fk_activity_logs_user_id', 'activity_logs', type_='foreignkey')
    op.create_foreign_key(op.f('activity_logs_user_id_fkey'), 'activity_logs', 'users', ['user_id'], ['id'], ondelete='CASCADE')
    op.alter_column('activity_logs', 'user_id', existing_type=sa.INTEGER(), nullable=False)
    op.drop_index('ix_activity_logs_tenant_user_created', table_name='activity_logs')
    op.drop_index(op.f('ix_activity_logs_tenant_id'), table_name='activity_logs')
    op.drop_index('ix_activity_logs_tenant_created', table_name='activity_logs')
    op.drop_index('ix_activity_logs_tenant_action', table_name='activity_logs')
    op.drop_index('ix_activity_logs_target', table_name='activity_logs')
    op.create_index(op.f('ix_activity_logs_user_created'), 'activity_logs', ['user_id', 'created_at'], unique=False)
    op.drop_column('activity_logs', 'tenant_id')
