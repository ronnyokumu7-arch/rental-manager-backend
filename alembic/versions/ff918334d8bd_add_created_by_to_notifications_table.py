"""add created_by to notifications table

Revision ID: ff918334d8bd
Revises: 81253044ccb1
Create Date: 2026-11-15 12:05:30.993146

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ff918334d8bd'
down_revision: Union[str, Sequence[str], None] = '81253044ccb1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Add the column (nullable=True to be safe with existing rows, though table is likely empty)
    op.add_column('notifications', sa.Column('created_by', sa.Integer(), nullable=True))
    
    # 2. Add the foreign key constraint matching the AuditMixin design
    op.create_foreign_key(
        'fk_notifications_created_by_users', 
        'notifications', 'users', 
        ['created_by'], ['id'], 
        ondelete='SET NULL'
    )
    
    # 3. Add the index for performance
    op.create_index('ix_notifications_created_by', 'notifications', ['created_by'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Reverse the operations in opposite order
    
    # 1. Drop the index
    op.drop_index('ix_notifications_created_by', table_name='notifications')
    
    # 2. Drop the foreign key constraint
    op.drop_constraint('fk_notifications_created_by_users', 'notifications', type_='foreignkey')
    
    # 3. Drop the column
    op.drop_column('notifications', 'created_by')
