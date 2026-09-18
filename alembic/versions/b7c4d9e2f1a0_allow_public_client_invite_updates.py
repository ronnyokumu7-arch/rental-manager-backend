"""allow public client invite updates

Revision ID: b7c4d9e2f1a0
Revises: 8a1f4c7d2e90
Create Date: 2026-09-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "b7c4d9e2f1a0"
down_revision: Union[str, Sequence[str], None] = "8a1f4c7d2e90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE POLICY public_client_invite_token_update ON client_invites
        FOR UPDATE
        USING (token = app_public_token())
        WITH CHECK (token = app_public_token())
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS public_client_invite_token_update ON client_invites"
    )