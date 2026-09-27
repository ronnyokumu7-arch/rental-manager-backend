"""add investor contracts table

Revision ID: 19083e887ad2
Revises: 89fc0e855165
Create Date: 2026-09-27 21:16:31.797509

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '19083e887ad2'
down_revision: Union[str, Sequence[str], None] = '89fc0e855165'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Create the Enum type for PostgreSQL safely (ignores if it already exists)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE investorcontractstatus AS ENUM ('draft', 'pending_signature', 'signed', 'terminated');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    # 2. Create the Table
    op.create_table(
        'investor_contracts',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('vehicle_id', sa.Integer(), sa.ForeignKey('vehicles.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('booking_id', sa.Integer(), sa.ForeignKey('bookings.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('contract_number', sa.String(length=50), nullable=False),
        sa.Column('lease_rate', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('lease_rate_type', sa.String(length=20), nullable=False),
        sa.Column('duration_months', sa.Integer(), nullable=True),
        sa.Column('start_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.Enum('draft', 'pending_signature', 'signed', 'terminated', name='investorcontractstatus'), nullable=False, server_default='draft'),
        sa.Column('pdf_path', sa.String(length=500), nullable=True),
        sa.Column('share_token', sa.String(length=36), unique=True, nullable=True),
        sa.Column('share_token_expires_at', sa.DateTime(timezone=True), nullable=True),
        
        # Investor Signatures
        sa.Column('signed_by_investor', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('investor_signed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('investor_signature_path', sa.String(length=500), nullable=True),
        
        # Agency Signatures
        sa.Column('signed_by_agency', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('agency_signed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('agency_signature_path', sa.String(length=500), nullable=True),
        
        # AuditMixin columns
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        
        # Constraints
        sa.UniqueConstraint('tenant_id', 'contract_number', name='uq_tenant_investor_contract_number'),
        
        # Indexes
        sa.Index('ix_investor_contracts_tenant_created', 'tenant_id', 'created_at'),
        sa.Index('ix_investor_contracts_tenant_status', 'tenant_id', 'status'),
        sa.Index('ix_investor_contracts_vehicle_id', 'vehicle_id'),
        sa.Index('ix_investor_contracts_booking_id', 'booking_id'),
        sa.Index('ix_investor_contracts_token_expires', 'share_token', 'share_token_expires_at'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('investor_contracts')
    op.execute("DROP TYPE IF EXISTS investorcontractstatus")
