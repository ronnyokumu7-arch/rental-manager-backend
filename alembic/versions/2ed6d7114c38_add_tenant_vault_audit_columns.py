"""add_tenant_vault_audit_columns

Revision ID: 2ed6d7114c38
Revises: 9e0d985cc3a9
Create Date: 2026-09-07 21:17:34.855890

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2ed6d7114c38'
down_revision: Union[str, Sequence[str], None] = '9e0d985cc3a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ✅ Vault audit trail — written on archive/delete-soft, cleared on restore.
    # Gives the Vault view a "when" and "why" without digging into activity logs.
    op.add_column("tenants", sa.Column("vaulted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tenants", sa.Column("vault_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("tenants", "vault_reason")
    op.drop_column("tenants", "vaulted_at")
