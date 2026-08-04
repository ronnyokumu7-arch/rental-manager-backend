"""add_payment_verifications_table_and_tenant_billing_fields

Revision ID: cf32d5acfb18
Revises: fed3e970ec43
Create Date: 2026-07-21 11:28:40.276765

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'cf32d5acfb18'
down_revision: Union[str, Sequence[str], None] = 'fed3e970ec43'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Existing Postgres Enum type (prevent Alembic from attempting to recreate it)
    payment_method_enum = postgresql.ENUM(
        'mpesa', 'airtel_money', 'card', 'paypal', 'bank', 'manual',
        name='paymentmethod',
        create_type=False
    )

    op.create_table(
        'payment_verifications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('target_plan', sa.String(length=50), nullable=False),
        sa.Column('target_billing_cycle', sa.String(length=20), nullable=False),
        sa.Column('payment_method', payment_method_enum, nullable=False),
        sa.Column('reference_code', sa.String(length=100), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column(
            'status',
            sa.Enum('pending', 'approved', 'rejected', name='verificationstatus'),
            server_default='pending',
            nullable=False,
        ),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('reviewed_by_id', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['reviewed_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_payment_verifications_id'), 'payment_verifications', ['id'], unique=False)
    op.create_index(op.f('ix_payment_verifications_reference_code'), 'payment_verifications', ['reference_code'], unique=True)
    op.create_index(op.f('ix_payment_verifications_status'), 'payment_verifications', ['status'], unique=False)
    op.create_index(op.f('ix_payment_verifications_tenant_id'), 'payment_verifications', ['tenant_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_payment_verifications_tenant_id'), table_name='payment_verifications')
    op.drop_index(op.f('ix_payment_verifications_status'), table_name='payment_verifications')
    op.drop_index(op.f('ix_payment_verifications_reference_code'), table_name='payment_verifications')
    op.drop_index(op.f('ix_payment_verifications_id'), table_name='payment_verifications')
    op.drop_table('payment_verifications')

    # Safely drop the newly created verificationstatus enum
    verification_status_enum = postgresql.ENUM('pending', 'approved', 'rejected', name='verificationstatus')
    verification_status_enum.drop(op.get_bind(), checkfirst=True)
