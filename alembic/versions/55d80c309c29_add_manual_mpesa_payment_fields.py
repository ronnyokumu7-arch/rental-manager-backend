"""add_manual_mpesa_payment_fields

Revision ID: 55d80c309c29
Revises: eac04ee9beae
Create Date: 2026-08-16 22:05:09.165565

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '55d80c309c29'
down_revision: Union[str, Sequence[str], None] = 'eac04ee9beae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: allow manual-only M-Pesa configs + add payment detail columns."""
    # 1) Relax NOT NULL so tenants can configure manual payments without Daraja creds
    op.alter_column("mpesa_configs", "consumer_key", existing_type=sa.String(length=255), nullable=True)
    op.alter_column("mpesa_configs", "consumer_secret", existing_type=sa.String(length=255), nullable=True)
    op.alter_column("mpesa_configs", "passkey", existing_type=sa.String(length=255), nullable=True)
    op.alter_column("mpesa_configs", "business_shortcode", existing_type=sa.String(length=20), nullable=True)

    # 2) Add manual payment detail columns (server_default backfills existing rows)
    op.add_column("mpesa_configs", sa.Column("method_type", sa.String(length=20), nullable=False, server_default="paybill"))
    op.add_column("mpesa_configs", sa.Column("account_number", sa.String(length=100), nullable=True))
    op.add_column("mpesa_configs", sa.Column("account_name", sa.String(length=150), nullable=True))


def downgrade() -> None:
    """Downgrade schema: remove manual payment columns + restore NOT NULL."""
    op.drop_column("mpesa_configs", "account_name")
    op.drop_column("mpesa_configs", "account_number")
    op.drop_column("mpesa_configs", "method_type")

    op.alter_column("mpesa_configs", "business_shortcode", existing_type=sa.String(length=20), nullable=False)
    op.alter_column("mpesa_configs", "passkey", existing_type=sa.String(length=255), nullable=False)
    op.alter_column("mpesa_configs", "consumer_secret", existing_type=sa.String(length=255), nullable=False)
    op.alter_column("mpesa_configs", "consumer_key", existing_type=sa.String(length=255), nullable=False)
