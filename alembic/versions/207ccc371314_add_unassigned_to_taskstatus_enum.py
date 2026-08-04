"""add_unassigned_to_taskstatus_enum

Revision ID: 207ccc371314
Revises: ea2376c95173
Create Date: 2026-07-07 18:54:37.063795

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '207ccc371314'
down_revision: Union[str, Sequence[str], None] = 'ea2376c95173'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Safely add 'unassigned' to taskstatus enum only if it doesn't exist
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_enum 
                WHERE enumlabel = 'unassigned' 
                AND enumtypid = 'taskstatus'::regtype
            ) THEN
                ALTER TYPE taskstatus ADD VALUE 'unassigned';
            END IF;
        END
        $$;
    """)


def downgrade() -> None:
    """Downgrade schema."""
    # PostgreSQL doesn't support dropping enum values easily, so we leave it as a no-op
    pass
