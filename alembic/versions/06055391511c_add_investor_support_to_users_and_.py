"""add_investor_support_to_users_and_vehicles

Revision ID: 06055391511c
Revises: c2d8e4f6a1b3
Create Date: 2026-09-21 22:22:20.448972

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '06055391511c'
down_revision: Union[str, Sequence[str], None] = 'c2d8e4f6a1b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    
    # 1. Add 'investor' to the existing UserRole enum (PostgreSQL)
    op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'investor'")

    # 2. Add Financial/Payout fields to Users table
    op.add_column('users', sa.Column('mpesa_phone', sa.String(length=50), nullable=True))
    op.add_column('users', sa.Column('bank_name', sa.String(length=100), nullable=True))
    op.add_column('users', sa.Column('bank_account_number', sa.String(length=100), nullable=True))
    op.add_column('users', sa.Column('bank_account_name', sa.String(length=100), nullable=True))

    # 3. Add Investor Ownership link to Vehicles table
    op.add_column('vehicles', sa.Column('owner_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True))
    
    # 4. Update daily_rate default to 0 (so investor cars can be saved without a rate)
    op.alter_column('vehicles', 'daily_rate',
               existing_type=sa.NUMERIC(precision=10, scale=2),
               existing_nullable=False,
               server_default='0')

    # 5. Create Indexes for Vehicles performance
    op.create_index('ix_vehicles_owner_id', 'vehicles', ['owner_id'])

    # 6. Create the new Investor Leases table
    op.create_table(
        'investor_leases',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('investor_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('vehicle_id', sa.Integer(), sa.ForeignKey('vehicles.id', ondelete='SET NULL'), nullable=True),
        
        # Lease Details
        sa.Column('lease_type', sa.Enum('pay_per_booking', 'fixed_monthly', name='leasetype'), nullable=False),
        sa.Column('rate_amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('duration_months', sa.Integer(), nullable=False),
        sa.Column('start_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_date', sa.DateTime(timezone=True), nullable=False),
        
        # Signatures
        sa.Column('investor_signed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('agency_signed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.Enum('draft', 'pending_signature', 'active', 'terminated', name='leasestatus'), nullable=False, server_default='draft'),
        
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )

    # 7. Create Indexes for Investor Leases performance
    op.create_index('ix_investor_leases_investor_id', 'investor_leases', ['investor_id'])
    op.create_index('ix_investor_leases_tenant_id', 'investor_leases', ['tenant_id'])
    op.create_index('ix_investor_leases_vehicle_id', 'investor_leases', ['vehicle_id'])


def downgrade() -> None:
    """Downgrade schema."""
    
    # 1. Drop Indexes
    op.drop_index('ix_investor_leases_vehicle_id', table_name='investor_leases')
    op.drop_index('ix_investor_leases_tenant_id', table_name='investor_leases')
    op.drop_index('ix_investor_leases_investor_id', table_name='investor_leases')
    op.drop_index('ix_vehicles_owner_id', table_name='vehicles')

    # 2. Drop Tables
    op.drop_table('investor_leases')
    
    # Note: We leave the custom Enum types ('leasetype', 'leasestatus') in the DB 
    # during downgrade to prevent cascading errors, but they won't be used.

    # 3. Drop Vehicle columns & revert default
    op.drop_column('vehicles', 'owner_id')
    op.alter_column('vehicles', 'daily_rate',
               existing_type=sa.NUMERIC(precision=10, scale=2),
               existing_nullable=False,
               server_default=None) # Reverts to no default, or you can set it back to original if it had one

    # 4. Drop User columns
    op.drop_column('users', 'bank_account_name')
    op.drop_column('users', 'bank_account_number')
    op.drop_column('users', 'bank_name')
    op.drop_column('users', 'mpesa_phone')

    # Note: Removing 'investor' from the userrole enum is complex in Postgres 
    # (requires recreating the type). We leave it in the enum during downgrade.
