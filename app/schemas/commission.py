# app/schemas/commission.py
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.commission import CommissionStatus


class CommissionEventOut(BaseModel):
    """
    A single commission event = one started trip.
    Used by the tenant's commission history page and the super admin ledger.
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    booking_id: int
    amount: Decimal
    currency_code: str
    status: CommissionStatus
    trip_started_at: datetime
    paid_at: Optional[datetime] = None
    payment_reference: Optional[str] = None
    created_at: datetime


class CommissionSummaryOut(BaseModel):
    """
    The daily-resetting commission picture shown on the tenant dashboard.

    - today_*      → resets to 0 at 00:00H (computed from trip_started_at)
    - outstanding_* → the "tagged below" unpaid balance from previous days
    - soft_locked  → drives the "burner" banner + operational block
    """
    currency_code: str = "KES"

    # ✅ Today's counter (resets at 00:00H)
    today_count: int = 0
    today_total: Decimal = Decimal("0")

    # ✅ Unpaid balance from previous days (the "tag" under today's count)
    outstanding_count: int = 0
    outstanding_balance: Decimal = Decimal("0")

    # ✅ Grace-period / soft-lock state
    oldest_unpaid_at: Optional[datetime] = None
    grace_days: int = 3
    days_until_lock: Optional[int] = None   # <= 0 means locked
    soft_locked: bool = False
