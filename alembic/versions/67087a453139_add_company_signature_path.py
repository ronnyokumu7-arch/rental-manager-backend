"""add_company_signature_path

Revision ID: 67087a453139
Revises: c00c9ab74b17
Create Date: 2026-11-22 01:26:00.056435

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '67087a453139'
down_revision: Union[str, Sequence[str], None] = 'c00c9ab74b17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('tenant_profiles', sa.Column('company_signature_path', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('tenant_profiles', 'company_signature_path')
