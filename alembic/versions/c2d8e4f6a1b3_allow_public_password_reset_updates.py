"""allow public password reset updates

Revision ID: c2d8e4f6a1b3
Revises: b7c4d9e2f1a0
Create Date: 2026-09-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "c2d8e4f6a1b3"
down_revision: Union[str, Sequence[str], None] = "b7c4d9e2f1a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE POLICY public_user_password_reset_update ON users
        FOR UPDATE
        USING (id = app_public_user_id())
        WITH CHECK (id = app_public_user_id())
        """
    )
    op.execute(
        """
        CREATE POLICY public_user_refresh_token_revoke ON refresh_tokens
        FOR UPDATE
        USING (user_id = app_public_user_id())
        WITH CHECK (user_id = app_public_user_id())
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS public_user_refresh_token_revoke ON refresh_tokens"
    )
    op.execute(
        "DROP POLICY IF EXISTS public_user_password_reset_update ON users"
    )