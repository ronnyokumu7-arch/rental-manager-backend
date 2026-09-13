"""fix RLS authentication bootstrap

Revision ID: 8a1f4c7d2e90
Revises: 5fd24a425f0b
Create Date: 2026-09-13 17:20:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "8a1f4c7d2e90"
down_revision: Union[str, Sequence[str], None] = "5fd24a425f0b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION app_public_token_hash() RETURNS text
        LANGUAGE sql STABLE AS $$
            SELECT NULLIF(current_setting('app.public_token_hash', true), '')
        $$;

        CREATE POLICY public_refresh_token_hash ON refresh_tokens
        FOR SELECT USING (token_hash = app_public_token_hash());
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS public_refresh_token_hash ON refresh_tokens")
    op.execute("DROP FUNCTION IF EXISTS app_public_token_hash()")