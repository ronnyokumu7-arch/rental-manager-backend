"""add_notifications_table

Revision ID: 81253044ccb1
Revises: d4e5f6a7b8c9
Create Date: 2026-11-08 21:17:46.870731

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '81253044ccb1'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ✅ 1. Create Enums safely using PostgreSQL DO blocks.
    # This is the standard, correct way to handle "create if not exists" for ENUMs in Postgres.
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE notificationtype AS ENUM ('booking', 'payment', 'client', 'vehicle', 'system', 'alert');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE notificationpriority AS ENUM ('low', 'normal', 'high');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    # 2. Create Table
    # create_type=False is critical here so SQLAlchemy doesn't try to create the ENUM again
    op.create_table(
        'notifications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('type', postgresql.ENUM(name='notificationtype', create_type=False), nullable=False),
        sa.Column('priority', postgresql.ENUM(name='notificationpriority', create_type=False), nullable=False, server_default='normal'),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default=sa.text("'{}'::jsonb")),
        sa.Column('action_url', sa.String(length=500), nullable=True),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # 3. Create Indexes
    op.create_index('ix_notifications_id', 'notifications', ['id'], unique=False)
    op.create_index('ix_notifications_tenant_id', 'notifications', ['tenant_id'], unique=False)
    op.create_index('ix_notifications_user_id', 'notifications', ['user_id'], unique=False)
    op.create_index('ix_notifications_type', 'notifications', ['type'], unique=False)
    
    # Composite indexes for high-performance unread counts and filtering
    op.create_index('ix_notifications_user_unread', 'notifications', ['user_id', 'is_read', 'created_at'], unique=False)
    op.create_index('ix_notifications_tenant_type', 'notifications', ['tenant_id', 'type', 'created_at'], unique=False)


def downgrade() -> None:
    # 1. Drop Indexes
    op.drop_index('ix_notifications_tenant_type', table_name='notifications')
    op.drop_index('ix_notifications_user_unread', table_name='notifications')
    op.drop_index('ix_notifications_type', table_name='notifications')
    op.drop_index('ix_notifications_user_id', table_name='notifications')
    op.drop_index('ix_notifications_tenant_id', table_name='notifications')
    op.drop_index('ix_notifications_id', table_name='notifications')

    # 2. Drop Table
    op.drop_table('notifications')

    # 3. Drop Enums
    op.execute("DROP TYPE IF EXISTS notificationtype")
    op.execute("DROP TYPE IF EXISTS notificationpriority")
