"""force_all_tenants_to_pay_as_you_go_with_trial

Revision ID: d61e6d9e02c1
Revises: 5d5bf6ace47c
Create Date: 2026-08-18 07:56:50.491438

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd61e6d9e02c1'
down_revision: Union[str, Sequence[str], None] = '5d5bf6ace47c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    ✅ FORCE ALL TEST TENANTS TO PAYG + 30-DAY TRIAL + CLEAN SLATE
    """
    # 1. Tenants → PAYG + fresh 30-day trial
    op.execute("""
        UPDATE tenants
        SET plan = 'pay_as_you_go',
            subscription_status = 'trial',
            trial_ends_at = now() + interval '30 days',
            updated_at = now()
        WHERE is_archived = false
    """)

    # 2. Each tenant's latest subscription record → keep it consistent
    op.execute("""
        UPDATE subscriptions s
        SET plan = 'pay_as_you_go',
            billing_cycle = 'pay_as_you_go',
            status = 'trial',
            starts_at = now(),
            ends_at = now() + interval '30 days',
            updated_at = now()
        WHERE s.id = (
          SELECT id FROM subscriptions
          WHERE tenant_id = s.tenant_id
          ORDER BY created_at DESC LIMIT 1
        )
    """)

    # 3. Clean slate: waive all unpaid commission events (test debts)
    op.execute("""
        UPDATE commission_events
        SET status = 'waived', updated_at = now()
        WHERE status = 'unpaid'
    """)


def downgrade() -> None:
    """
    Downgrade is destructive — we cannot reliably restore the original
    test plan/billing/status for each tenant. Manual rollback if needed.
    """
    pass
