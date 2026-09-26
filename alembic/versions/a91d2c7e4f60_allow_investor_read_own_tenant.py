"""allow investors to read their associated tenant

Revision ID: a91d2c7e4f60
Revises: 8bc24f60d191
Create Date: 2026-09-26

"""
from typing import Sequence, Union

from alembic import op


revision: str = "a91d2c7e4f60"
down_revision: Union[str, Sequence[str], None] = "8bc24f60d191"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE POLICY investor_read_associated_tenant ON tenants
        FOR SELECT
        USING (
            app_is_investor()
            AND id = app_current_tenant_id()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS investor_read_associated_tenant ON tenants")