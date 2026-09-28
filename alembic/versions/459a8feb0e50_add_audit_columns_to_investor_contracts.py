"""add_audit_columns_to_investor_contracts

Revision ID: 459a8feb0e50
Revises: 19083e887ad2
Create Date: 2026-09-28 21:58:02.641615

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '459a8feb0e50'
down_revision: Union[str, Sequence[str], None] = '19083e887ad2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add missing AuditMixin columns to investor_contracts."""
    # Check if columns exist before adding to be 100% safe
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('investor_contracts')]
    
    if 'created_by' not in columns:
        op.add_column('investor_contracts', sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True))
    
    if 'updated_by' not in columns:
        op.add_column('investor_contracts', sa.Column('updated_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True))


def downgrade() -> None:
    """Remove audit columns."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('investor_contracts')]
    
    if 'updated_by' in columns:
        op.drop_column('investor_contracts', 'updated_by')
    if 'created_by' in columns:
        op.drop_column('investor_contracts', 'created_by')
