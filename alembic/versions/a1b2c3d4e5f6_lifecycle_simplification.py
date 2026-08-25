"""lifecycle simplification: 5-state booking/vehicle + quotation doc_type

Revision ID: a1b2c3d4e5f6
Revises: 999fe8651bf8
Create Date: 2026-08-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '999fe8651bf8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Add columns (all server-defaulted / nullable → non-blocking) ──
    op.add_column('bookings', sa.Column('cancellation_reason', sa.String(length=30), nullable=True))
    op.add_column('bookings', sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('bookings', sa.Column('cancelled_by', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_bookings_cancelled_by_user', 'bookings', 'users',
        ['cancelled_by'], ['id'], ondelete='SET NULL',
    )

    op.add_column('vehicles', sa.Column(
        'mileage_due', sa.Boolean(), nullable=False, server_default=sa.text('false'),
    ))

    op.add_column('invoices', sa.Column(
        'doc_type', sa.String(length=20), nullable=False, server_default=sa.text("'invoice'"),
    ))

    # ── 2. Indexes for the new operational views ──
    op.create_index('ix_vehicles_tenant_mileage_due', 'vehicles', ['tenant_id', 'mileage_due'])
    op.create_index('ix_invoices_booking_doctype', 'invoices', ['booking_id', 'doc_type'])

    # ── 3. BACKFILL (runs before new code boots) ──
    # no_show → cancelled + reason (preserve the signal as data)
    op.execute(
        "UPDATE bookings SET status='cancelled', cancellation_reason='no_show', "
        "cancelled_at=COALESCE(cancelled_at, updated_at, now()) "
        "WHERE status='no_show'"
    )
    # awaiting_mileage → available + mileage_due (un-stick the fleet)
    op.execute(
        "UPDATE vehicles SET status='available', mileage_due=true "
        "WHERE status='awaiting_mileage'"
    )
    # NOTE: invoices.doc_type is filled to 'invoice' by server_default on ADD COLUMN.
    # NOTE: We do NOT drop the old Postgres enum labels (no_show / awaiting_mileage) —
    # Postgres can't drop enum values safely; unused labels are harmless once backfilled.


def downgrade() -> None:
    # Restore prior states where recoverable
    op.execute(
        "UPDATE bookings SET status='no_show' "
        "WHERE status='cancelled' AND cancellation_reason='no_show'"
    )
    op.execute(
        "UPDATE vehicles SET status='awaiting_mileage' "
        "WHERE mileage_due=true AND status='available'"
    )

    op.drop_index('ix_invoices_booking_doctype', table_name='invoices')
    op.drop_index('ix_vehicles_tenant_mileage_due', table_name='vehicles')

    op.drop_constraint('fk_bookings_cancelled_by_user', 'bookings', type_='foreignkey')
    op.drop_column('bookings', 'cancelled_by')
    op.drop_column('bookings', 'cancelled_at')
    op.drop_column('bookings', 'cancellation_reason')
    op.drop_column('vehicles', 'mileage_due')
    op.drop_column('invoices', 'doc_type')
