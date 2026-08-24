"""add_uploaded_files_to_client_invites

Revision ID: 999fe8651bf8
Revises: dd610400ab04
Create Date: 2026-08-24 12:01:41.887480

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '999fe8651bf8'
down_revision: Union[str, Sequence[str], None] = 'dd610400ab04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add uploaded_files JSON column to client_invites for slot-upsert tracking."""
    op.add_column('client_invites', sa.Column('uploaded_files', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Remove uploaded_files column."""
    op.drop_column('client_invites', 'uploaded_files')
