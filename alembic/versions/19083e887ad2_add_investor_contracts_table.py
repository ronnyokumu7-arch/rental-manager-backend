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
    """Upgrade schema using 100% raw SQL to bypass SQLAlchemy metadata issues."""
    
    # 1. Create Enum safely (natively ignores if it already exists)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE investorcontractstatus AS ENUM ('draft', 'pending_signature', 'signed', 'terminated');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    # 2. Create Table safely (natively ignores if it already exists)
    op.execute("""
        CREATE TABLE IF NOT EXISTS investor_contracts (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            vehicle_id INTEGER NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
            booking_id INTEGER REFERENCES bookings(id) ON DELETE SET NULL,
            contract_number VARCHAR(50) NOT NULL,
            lease_rate NUMERIC(10, 2) NOT NULL,
            lease_rate_type VARCHAR(20) NOT NULL,
            duration_months INTEGER,
            start_date TIMESTAMP WITH TIME ZONE NOT NULL,
            end_date TIMESTAMP WITH TIME ZONE NOT NULL,
            status investorcontractstatus NOT NULL DEFAULT 'draft',
            pdf_path VARCHAR(500),
            share_token VARCHAR(36) UNIQUE,
            share_token_expires_at TIMESTAMP WITH TIME ZONE,
            signed_by_investor BOOLEAN NOT NULL DEFAULT FALSE,
            investor_signed_at TIMESTAMP WITH TIME ZONE,
            investor_signature_path VARCHAR(500),
            signed_by_agency BOOLEAN NOT NULL DEFAULT FALSE,
            agency_signed_at TIMESTAMP WITH TIME ZONE,
            agency_signature_path VARCHAR(500),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_tenant_investor_contract_number UNIQUE (tenant_id, contract_number)
        );
    """)

    # 3. Create Indexes safely (natively ignores if they already exist)
    op.execute("CREATE INDEX IF NOT EXISTS ix_investor_contracts_tenant_created ON investor_contracts (tenant_id, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_investor_contracts_tenant_status ON investor_contracts (tenant_id, status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_investor_contracts_vehicle_id ON investor_contracts (vehicle_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_investor_contracts_booking_id ON investor_contracts (booking_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_investor_contracts_token_expires ON investor_contracts (share_token, share_token_expires_at)")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE IF EXISTS investor_contracts")
    op.execute("DROP TYPE IF EXISTS investorcontractstatus")
