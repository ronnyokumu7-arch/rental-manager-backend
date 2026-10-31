"""add client-owned driver fields

Revision ID: ccce4687d7e4
Revises: 76d65f28e9a4
Create Date: 2026-10-31 18:00:03.418060

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ccce4687d7e4'
down_revision: Union[str, Sequence[str], None] = '76d65f28e9a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ✅ CLIENT-OWNED PERSONAL DRIVER (own_driver arrangement only)
    # These columns store the client's personal driver inline on the client
    # record — the client endpoint is the single source of truth.
    op.add_column(
        "clients",
        sa.Column("driver_full_name", sa.String(length=150), nullable=True),
    )
    op.add_column(
        "clients",
        sa.Column("driver_phone", sa.String(length=30), nullable=True),
    )
    op.add_column(
        "clients",
        sa.Column("driver_id_number", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "clients",
        sa.Column("driver_dl_number", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "clients",
        sa.Column("driver_dl_expiry", sa.Date(), nullable=True),
    )
    op.add_column(
        "clients",
        sa.Column("driver_dl_issued_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "clients",
        sa.Column("driver_id_image_front", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "clients",
        sa.Column("driver_dl_image_front", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("clients", "driver_dl_image_front")
    op.drop_column("clients", "driver_id_image_front")
    op.drop_column("clients", "driver_dl_issued_date")
    op.drop_column("clients", "driver_dl_expiry")
    op.drop_column("clients", "driver_dl_number")
    op.drop_column("clients", "driver_id_number")
    op.drop_column("clients", "driver_phone")
    op.drop_column("clients", "driver_full_name")
