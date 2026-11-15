"""add contract notification type

Revision ID: 13f3fa221efc
Revises: ff918334d8bd
Create Date: 2026-11-15 16:32:07.345751

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '13f3fa221efc'
down_revision: Union[str, Sequence[str], None] = 'ff918334d8bd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ⚠️ VERIFY: Check your actual Postgres enum type name. 
    # SQLAlchemy defaults to the class name lowercased ('notificationtype').
    # If your previous migrations named it differently (e.g., 'notification_type'),
    # update the string below. The migration will fail safely if the name is wrong.
    enum_type = "notificationtype"

    # ADD VALUE cannot run inside a transaction on older Postgres versions, 
    # and the new value cannot be used in the same transaction that adds it.
    # The autocommit block is the canonical, safe way to handle this.
    with op.get_context().autocommit_block():
        op.execute(
            sa.text(
                "ALTER TYPE {t} ADD VALUE IF NOT EXISTS 'contract'".format(t=enum_type)
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    # Postgres does not support dropping a single value from an existing ENUM type.
    # The only way to remove it is to recreate the entire type and alter the column,
    # which is highly destructive and risks data loss. 
    # Leaving the unused 'contract' value in the enum is the safest and standard approach.
    pass
