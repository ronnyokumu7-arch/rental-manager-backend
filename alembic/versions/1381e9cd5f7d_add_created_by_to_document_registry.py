"""add_created_by_to_document_registry

Revision ID: 1381e9cd5f7d
Revises: bd04721fd987
Create Date: 2026-10-10 22:19:44.425643

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1381e9cd5f7d'
down_revision: Union[str, Sequence[str], None] = 'bd04721fd987'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ✅ Add the created_by column matching the AuditMixin
    op.add_column(
        'document_registry',
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    )
    
    # ✅ Add the index for performance (matching the mixin)
    op.create_index(
        op.f('ix_document_registry_created_by'), 
        'document_registry', 
        ['created_by'], 
        unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    # ✅ Reverse the changes safely
    op.drop_index(op.f('ix_document_registry_created_by'), table_name='document_registry')
    op.drop_column('document_registry', 'created_by')
