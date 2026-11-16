"""add contract_terms to tenant_profiles

Revision ID: f931ca9f4b14
Revises: 13f3fa221efc
Create Date: 2026-11-17 00:39:35.951634

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f931ca9f4b14'
down_revision: Union[str, Sequence[str], None] = '13f3fa221efc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('tenant_profiles', sa.Column('contract_terms', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('tenant_profiles', 'contract_terms')
