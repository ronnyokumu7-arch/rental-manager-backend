"""add self-drive pricing snapshot columns + activity log columns

Revision ID: 5f79250155ac
Revises: a1b2c3d4e5f6
Create Date: 2026-08-29 13:05:10.179333

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = '5f79250155ac'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ── Additive Phase 1 columns ─────────────────────────────────────────
    op.add_column(
        "bookings",
        sa.Column("billable_days", sa.Integer(), nullable=True),
    )
    op.add_column(
        "bookings",
        sa.Column("computed_total", sa.Numeric(precision=10, scale=2), nullable=True),
    )
    op.add_column(
        "bookings",
        sa.Column(
            "manually_adjusted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),   # existing rows default to false
        ),
    )
    op.add_column(
        "bookings",
        sa.Column("price_note", sa.Text(), nullable=True),
    )

    # ── ✅ NEW: Activity Log columns ─────────────────────────────────────
    op.add_column(
        "activity_logs",
        sa.Column("label", sa.String(length=255), nullable=False, server_default="Activity"),
    )
    op.add_column(
        "activity_logs",
        sa.Column("summary", JSONB(), nullable=True),
    )
    op.add_column(
        "activity_logs",
        sa.Column("priority", sa.Integer(), nullable=False, server_default="2"),
    )

    # ✅ NEW: Add index for priority sorting (Dashboard "Critical" feed)
    op.create_index(
        "ix_activity_logs_tenant_priority_created",
        "activity_logs",
        ["tenant_id", "priority", "created_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    # ── Clean reverse order ──────────────────────────────────────────────
    # Drop the new Activity Log index first
    op.drop_index("ix_activity_logs_tenant_priority_created", table_name="activity_logs")

    # Drop Activity Log columns
    op.drop_column("activity_logs", "priority")
    op.drop_column("activity_logs", "summary")
    op.drop_column("activity_logs", "label")

    # Drop Booking columns
    op.drop_column("bookings", "price_note")
    op.drop_column("bookings", "manually_adjusted")
    op.drop_column("bookings", "computed_total")
    op.drop_column("bookings", "billable_days")
