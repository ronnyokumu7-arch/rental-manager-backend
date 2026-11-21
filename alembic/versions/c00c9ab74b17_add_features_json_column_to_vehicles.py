"""add features json to vehicles and handover columns to contracts

Revision ID: c00c9ab74b17
Revises: f931ca9f4b14
Create Date: 2026-11-21 13:43:08.881119

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c00c9ab74b17'
down_revision: Union[str, Sequence[str], None] = 'f931ca9f4b14'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Add features to vehicles
    op.add_column('vehicles', sa.Column('features', sa.JSON(), nullable=True, server_default='[]'))

    # 2. Add handover checklist fields to contracts
    op.add_column('contracts', sa.Column('handover_items', sa.JSON(), nullable=True, server_default='[]'))
    op.add_column('contracts', sa.Column('handover_checklist', sa.JSON(), nullable=True))
    op.add_column('contracts', sa.Column('handover_signature_image_path', sa.String(length=500), nullable=True))
    op.add_column('contracts', sa.Column('handover_signed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Drop contracts columns (reverse order)
    op.drop_column('contracts', 'handover_signed_at')
    op.drop_column('contracts', 'handover_signature_image_path')
    op.drop_column('contracts', 'handover_checklist')
    op.drop_column('contracts', 'handover_items')
    
    # Drop vehicles column
    op.drop_column('vehicles', 'features')
