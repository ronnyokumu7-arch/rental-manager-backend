"""retroactively assign owner_id and auto-verify existing tenant admins

Revision ID: cb0ad871e9f6
Revises: aa49a23fcdd4
Create Date: 2026-07-19 18:51:57.189561

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cb0ad871e9f6'
down_revision: Union[str, Sequence[str], None] = 'aa49a23fcdd4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    
    # 1. Find the earliest tenant_admin for each tenant and set them as the owner.
    # Only updates tenants that don't have an owner yet.
    op.execute("""
        UPDATE tenants
        SET owner_id = (
            SELECT id FROM users 
            WHERE users.tenant_id = tenants.id 
            AND users.role = 'tenant_admin' 
            ORDER BY users.created_at ASC 
            LIMIT 1
        )
        WHERE owner_id IS NULL;
    """)
    
    # 2. Auto-verify those newly assigned owners (bypass the invite flow).
    # Only updates users who were just assigned as an owner.
    op.execute("""
        UPDATE users
        SET is_onboarded = true,
            email_verified = true,
            phone_verified = true
        WHERE id IN (
            SELECT owner_id FROM tenants WHERE owner_id IS NOT NULL
        );
    """)


def downgrade() -> None:
    """Downgrade schema."""
    
    # Revert the auto-verification for the users who were assigned as owners
    op.execute("""
        UPDATE users
        SET is_onboarded = false,
            email_verified = false,
            phone_verified = false
        WHERE id IN (
            SELECT owner_id FROM tenants WHERE owner_id IS NOT NULL
        );
    """)
    
    # Remove the owner links
    op.execute("UPDATE tenants SET owner_id = NULL;")
