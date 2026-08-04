"""add_compliance_and_jsonb

Revision ID: fb1756fb095d
Revises: 
Create Date: 2026-07-06 16:04:03.505415

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'fb1756fb095d'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add new compliance columns
    op.add_column('users', sa.Column('id_number', sa.String(), nullable=True))
    op.add_column('users', sa.Column('dl_number', sa.String(), nullable=True))
    op.add_column('users', sa.Column('dl_expiry', sa.Date(), nullable=True))
    
    # 2. Safely upgrade 'permissions' from JSON to JSONB
    # Step A: Drop the old JSON default so Postgres allows the type change
    op.alter_column(
        'users', 'permissions',
        existing_type=postgresql.JSON(astext_type=sa.Text()),
        server_default=None
    )
    
    # Step B: Change the column type to JSONB using the PostgreSQL 'USING' clause
    op.alter_column(
        'users', 'permissions',
        type_=postgresql.JSONB(astext_type=sa.Text()),
        postgresql_using='permissions::jsonb'
    )
    
    # Step C: Apply the new JSONB server default
    op.alter_column(
        'users', 'permissions',
        server_default=sa.text("'[]'::jsonb")
    )


def downgrade() -> None:
    # 1. Revert 'permissions' back to JSON
    op.alter_column(
        'users', 'permissions',
        server_default=None
    )
    
    op.alter_column(
        'users', 'permissions',
        type_=postgresql.JSON(astext_type=sa.Text()),
        postgresql_using='permissions::json'
    )
    
    op.alter_column(
        'users', 'permissions',
        server_default=sa.text("'[]'::json")
    )
    
    # 2. Drop compliance columns
    op.drop_column('users', 'dl_expiry')
    op.drop_column('users', 'dl_number')
    op.drop_column('users', 'id_number')
