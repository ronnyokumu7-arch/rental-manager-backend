"""add pending client driving arrangement

Revision ID: d4e5f6a7b8c9
Revises: ccce4687d7e4
Create Date: 2026-11-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "ccce4687d7e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE clients DROP CONSTRAINT IF EXISTS ck_clients_driving_arrangement_valid")
    op.execute(
        "ALTER TABLE clients ADD CONSTRAINT ck_clients_driving_arrangement_valid "
        "CHECK (driving_arrangement IN ('pending', 'self_drive', 'own_driver', 'chauffeur'))"
    )
    op.execute("ALTER TABLE clients ALTER COLUMN driving_arrangement SET DEFAULT 'pending'")


def downgrade() -> None:
    op.execute("UPDATE clients SET driving_arrangement = 'self_drive' WHERE driving_arrangement = 'pending'")
    op.execute("ALTER TABLE clients DROP CONSTRAINT IF EXISTS ck_clients_driving_arrangement_valid")
    op.execute(
        "ALTER TABLE clients ADD CONSTRAINT ck_clients_driving_arrangement_valid "
        "CHECK (driving_arrangement IN ('self_drive', 'own_driver', 'chauffeur'))"
    )
    op.execute("ALTER TABLE clients ALTER COLUMN driving_arrangement SET DEFAULT 'self_drive'")
