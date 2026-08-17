# app/schemas/commission_payment.py
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.commission_payment import CommissionPaymentStatus


class CommissionPaymentCreate(BaseModel):
    """Tenant submits an M-Pesa confirmation code for a commission payment."""
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    reference: str = Field(..., min_length=4, max_length=100)
    notes: Optional[str] = Field(default=None, max_length=500)


class CommissionPaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    amount: Decimal
    currency_code: str
    reference: str
    status: CommissionPaymentStatus
    verified_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime


class CommissionPaymentInfoOut(BaseModel):
    """Everything the /commission/pay page needs to render."""
    currency_code: str = "KES"

    # What they owe right now (ALL unpaid events, including today's)
    outstanding_balance: Decimal
    outstanding_count: int

    # Platform payment details (from PlatformSettings singleton)
    platform_paybill: Optional[str] = None
    platform_account_name: Optional[str] = None
    platform_phone: Optional[str] = None
    platform_email: Optional[str] = None

    # The reference the tenant should quote when paying (your matching key)
    payment_reference_hint: str

    # Latest submission awaiting verification (if any)
    pending_payment: Optional[CommissionPaymentOut] = None


class CommissionPaymentRejectIn(BaseModel):
    """Reason shown to the tenant when their code doesn't match."""
    notes: str = Field(..., min_length=3, max_length=500)


class CommissionPaymentVerifyResult(BaseModel):
    """Feedback for the admin UI after verifying."""
    payment: CommissionPaymentOut
    events_marked_paid: int
    unapplied_amount: Decimal
