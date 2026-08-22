"""add driver link columns to bookings

Revision ID: d5e6f7a8b9c0
Revises: fe6e52fc6f36
Create Date: 2026-08-22 07:45:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, Sequence[str], None] = 'fe6e52fc6f36'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Idempotent (IF NOT EXISTS) — safe if columns were added manually during incident."""
    op.execute("""
        ALTER TABLE bookings
          ADD COLUMN IF NOT EXISTS driver_id INTEGER,
          ADD COLUMN IF NOT EXISTS client_provided_driver BOOLEAN NOT NULL DEFAULT FALSE,
          ADD COLUMN IF NOT EXISTS client_driver_name VARCHAR(150),
          ADD COLUMN IF NOT EXISTS client_driver_phone VARCHAR(30)
    """)
    op.execute("""
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'bookings_driver_id_fkey') THEN
            ALTER TABLE bookings ADD CONSTRAINT bookings_driver_id_fkey
              FOREIGN KEY (driver_id) REFERENCES drivers(id) ON DELETE SET NULL;
          END IF;
        END $$;
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_bookings_driver_id ON bookings (driver_id)")
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_bookings_driver_availability
        ON bookings (tenant_id, driver_id, start_date, end_date)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_bookings_driver_availability")
    op.execute("DROP INDEX IF EXISTS ix_bookings_driver_id")
    op.execute("ALTER TABLE bookings DROP CONSTRAINT IF EXISTS bookings_driver_id_fkey")
    op.execute("""
        ALTER TABLE bookings
          DROP COLUMN IF EXISTS driver_id,
          DROP COLUMN IF EXISTS client_provided_driver,
          DROP COLUMN IF EXISTS client_driver_name,
          DROP COLUMN IF EXISTS client_driver_phone
    """)
