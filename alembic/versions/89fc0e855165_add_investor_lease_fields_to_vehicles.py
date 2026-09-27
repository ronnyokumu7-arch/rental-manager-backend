"""add investor lease fields to vehicles

Revision ID: 89fc0e855165
Revises: 4f5b34cb3350
Create Date: 2026-09-27 18:01:00.017509

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '89fc0e855165'
down_revision: Union[str, Sequence[str], None] = '4f5b34cb3350'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema safely (idempotent)."""
    op.execute("ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS investor_lease_rate NUMERIC(10, 2)")
    op.execute("ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS lease_rate_type VARCHAR(20) DEFAULT 'daily'")
    op.execute("ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS lease_rate_locked BOOLEAN DEFAULT FALSE")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE vehicles DROP COLUMN IF EXISTS lease_rate_locked")
    op.execute("ALTER TABLE vehicles DROP COLUMN IF EXISTS lease_rate_type")
    op.execute("ALTER TABLE vehicles DROP COLUMN IF EXISTS investor_lease_rate")
