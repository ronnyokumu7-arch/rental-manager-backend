"""seed_platform_settings_if_missing

Revision ID: 5d5bf6ace47c
Revises: d8f898a77f5b
Create Date: 2026-08-17 16:26:20.768792

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5d5bf6ace47c'
down_revision: Union[str, Sequence[str], None] = 'd8f898a77f5b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ✅ Idempotent seed: only inserts if the singleton row is missing.
    # Safe defaults only — real values are runtime data (SQL / admin UI).
    op.execute("""
        INSERT INTO platform_settings (
            id, commission_amount, grace_period_days,
            created_at, updated_at
        )
        SELECT 1, 150.00, 3, now(), now()
        WHERE NOT EXISTS (SELECT 1 FROM platform_settings WHERE id = 1)
    """)


def downgrade() -> None:
    """Downgrade schema."""
    # Data-only migration: leave rows untouched on downgrade.
    pass
