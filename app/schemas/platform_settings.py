# app/schemas/platform_settings.py
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PlatformSettingsOut(BaseModel):
    """Full platform settings view (super admin only)."""
    model_config = ConfigDict(from_attributes=True)

    id: int

    # ── PAYG engine knobs ─────────────────────────────────────
    commission_amount: Decimal
    grace_period_days: int

    # ── M-PESA PAYBILL TRIPLE ─────────────────────────────────
    platform_paybill: Optional[str] = None          # Business number (e.g., 400200)
    platform_account_number: Optional[str] = None   # Bank account behind the Paybill
    platform_account_name: Optional[str] = None     # Registered name (recipient confirmation)

    # ── Record keeping ────────────────────────────────────────
    platform_phone: Optional[str] = None
    platform_email: Optional[str] = None

    updated_at: datetime


class PlatformSettingsUpdate(BaseModel):
    """
    Super-admin editable fields. Full PUT — the form always sends the
    complete state, so the singleton row is fully replaced (no drift).
    """

    # ✅ Commission must be positive; grace 0 = "lock immediately", 30 = generous
    commission_amount: Decimal = Field(..., gt=0, decimal_places=2)
    grace_period_days: int = Field(..., ge=0, le=30)

    platform_paybill: Optional[str] = Field(None, max_length=50)
    platform_account_number: Optional[str] = Field(None, max_length=50)
    platform_account_name: Optional[str] = Field(None, max_length=150)
    platform_phone: Optional[str] = Field(None, max_length=30)
    platform_email: Optional[str] = Field(None, max_length=150)
