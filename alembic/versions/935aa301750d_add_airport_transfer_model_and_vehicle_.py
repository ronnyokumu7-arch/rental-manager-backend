"""add_airport_transfer_model_and_vehicle_transfer_fields

Revision ID: 935aa301750d
Revises: 5f79250155ac
Create Date: 2026-08-30 12:14:39.190821

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '935aa301750d'
down_revision: Union[str, Sequence[str], None] = '5f79250155ac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    
    # =========================================================================
    # 1. UPDATE VEHICLES TABLE
    # =========================================================================
    
    # --- Airport Transfer Fields ---
    op.add_column('vehicles', sa.Column('supports_airport_transfer', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('vehicles', sa.Column('airport_transfer_base_rate', sa.Numeric(10, 2), nullable=True))
    
    op.create_check_constraint(
        'ck_vehicles_airport_transfer_base_rate_non_negative',
        'vehicles',
        "(supports_airport_transfer = false) OR (airport_transfer_base_rate > 0)"
    )
    
    op.create_index('ix_vehicles_tenant_airport_transfer', 'vehicles', ['tenant_id', 'supports_airport_transfer'])

    # --- Wedding Service Fields (Milestone 3) ---
    op.add_column('vehicles', sa.Column('supports_wedding_service', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('vehicles', sa.Column('wedding_base_rate', sa.Numeric(10, 2), nullable=True))
    
    op.create_check_constraint(
        'ck_vehicles_wedding_base_rate_non_negative',
        'vehicles',
        "(supports_wedding_service = false) OR (wedding_base_rate > 0)"
    )
    
    op.create_index('ix_vehicles_tenant_wedding_service', 'vehicles', ['tenant_id', 'supports_wedding_service'])


    # =========================================================================
    # 2. CREATE AIRPORT_TRANSFERS TABLE
    # =========================================================================
    
    op.create_table('airport_transfers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('booking_id', sa.Integer(), sa.ForeignKey('bookings.id', ondelete='CASCADE'), nullable=False),
        sa.Column('flight_number', sa.String(20), nullable=True),
        sa.Column('airline', sa.String(50), nullable=True),
        sa.Column('terminal', sa.String(20), nullable=True),
        sa.Column('airport_code', sa.String(10), nullable=True),
        sa.Column('scheduled_pickup_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('flight_arrival_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('city', sa.String(100), nullable=True),
        sa.Column('pickup_location', sa.String(255), nullable=True),
        sa.Column('drop_off_location', sa.String(255), nullable=True),
        sa.Column('direction', sa.String(20), nullable=False, server_default='airport_pickup'),
        sa.Column('toll_fees', sa.Numeric(10, 2), nullable=False, server_default='0.00'),
        sa.Column('airport_parking_fees', sa.Numeric(10, 2), nullable=False, server_default='0.00'),
        sa.Column('notes', sa.Text(), nullable=True),
        # AuditMixin timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('booking_id')
    )
    
    # Add check constraints for financial fields
    op.create_check_constraint(
        'ck_airport_transfers_toll_fees_non_negative',
        'airport_transfers',
        'toll_fees >= 0'
    )
    op.create_check_constraint(
        'ck_airport_transfers_parking_fees_non_negative',
        'airport_transfers',
        'airport_parking_fees >= 0'
    )
    
    # Add indexes
    op.create_index('ix_airport_transfers_tenant_booking', 'airport_transfers', ['tenant_id', 'booking_id'])
    op.create_index('ix_airport_transfers_flight_number', 'airport_transfers', ['tenant_id', 'flight_number'])
    op.create_index('ix_airport_transfers_dispatch', 'airport_transfers', ['tenant_id', 'scheduled_pickup_at'])
    op.create_index('ix_airport_transfers_id', 'airport_transfers', ['id'])


    # =========================================================================
    # 3. UPDATE BOOKINGS TABLE
    # =========================================================================
    
    # --- Service Details JSON Field (Milestone 3) ---
    op.add_column('bookings', sa.Column('service_details', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    
    # =========================================================================
    # 1. DROP AIRPORT_TRANSFERS TABLE
    # =========================================================================
    
    # Drop indexes
    op.drop_index('ix_airport_transfers_id', table_name='airport_transfers')
    op.drop_index('ix_airport_transfers_dispatch', table_name='airport_transfers')
    op.drop_index('ix_airport_transfers_flight_number', table_name='airport_transfers')
    op.drop_index('ix_airport_transfers_tenant_booking', table_name='airport_transfers')
    
    # Drop constraints
    op.drop_constraint('ck_airport_transfers_parking_fees_non_negative', 'airport_transfers', type_='check')
    op.drop_constraint('ck_airport_transfers_toll_fees_non_negative', 'airport_transfers', type_='check')
    
    # Drop table
    op.drop_table('airport_transfers')


    # =========================================================================
    # 2. REVERT VEHICLES TABLE
    # =========================================================================
    
    # --- Revert Wedding Service Fields ---
    op.drop_index('ix_vehicles_tenant_wedding_service', table_name='vehicles')
    op.drop_constraint('ck_vehicles_wedding_base_rate_non_negative', 'vehicles', type_='check')
    op.drop_column('vehicles', 'wedding_base_rate')
    op.drop_column('vehicles', 'supports_wedding_service')

    # --- Revert Airport Transfer Fields ---
    op.drop_index('ix_vehicles_tenant_airport_transfer', table_name='vehicles')
    op.drop_constraint('ck_vehicles_airport_transfer_base_rate_non_negative', 'vehicles', type_='check')
    op.drop_column('vehicles', 'airport_transfer_base_rate')
    op.drop_column('vehicles', 'supports_airport_transfer')


    # =========================================================================
    # 3. REVERT BOOKINGS TABLE
    # =========================================================================
    
    # --- Revert Service Details JSON Field ---
    op.drop_column('bookings', 'service_details')
