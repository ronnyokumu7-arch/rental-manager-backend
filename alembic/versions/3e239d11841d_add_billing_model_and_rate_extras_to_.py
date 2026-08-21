"""add billing_model and rate_extras to pricing configs

Revision ID: 3e239d11841d
Revises: 843709a296eb
Create Date: 2026-08-21 18:12:08.899373

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '3e239d11841d'
down_revision: Union[str, Sequence[str], None] = '843709a296eb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. STRICTLY ADDITIVE — two nullable-safe columns."""
    with op.batch_alter_table('service_pricing_configs', schema=None) as batch_op:
        # ✅ Strategy selector: NULL → catalog default for this service
        batch_op.add_column(
            sa.Column('billing_model', sa.String(length=30), nullable=True)
        )
        # ✅ Flexible JSONB rate card (per_km, base_fare, fixed_rate,
        # half/full-day rates, min_charge_hours, route_rates, per_stop_rate)
        batch_op.add_column(
            sa.Column(
                'rate_extras',
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            )
        )


def downgrade() -> None:
    """Downgrade schema. Exact reverse of upgrade."""
    with op.batch_alter_table('service_pricing_configs', schema=None) as batch_op:
        batch_op.drop_column('rate_extras')
        batch_op.drop_column('billing_model')
