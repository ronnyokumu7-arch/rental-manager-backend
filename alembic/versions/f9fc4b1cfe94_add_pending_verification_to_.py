"""add pending_verification to subscription status

Revision ID: f9fc4b1cfe94
Revises: 1b8126c13299
Create Date: 2026-07-22 19:11:45.023566

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f9fc4b1cfe94'
down_revision: Union[str, Sequence[str], None] = '1b8126c13299'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
