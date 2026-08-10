from datetime import datetime
from decimal import Decimal
from typing import Any, Optional  # ✅ Added Any

from pydantic import BaseModel, computed_field, Field, field_validator, model_validator

from app.models.payments import PaymentMethod, PaymentStatus, VerificationStatus


class PaymentCreate(BaseModel):
    """
    Payload for recording a payment.
    ✅ SECURITY: 'status' is intentionally excluded. Status is controlled by the router.
    """
    amount: Decimal = Field(..., gt=0, decimal_places=2, description="Must be greater than 0")
    currency_code: str = Field(default="KES", min_length=3, max_length=3)
    method: PaymentMethod
    reference: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = Field(default=None, max_length=500)

    @field_validator("currency_code")
    @classmethod
    def normalize_currency_code(cls, v: str) -> str:
        return v.upper()


class PaymentVoid(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500, description="Reason for voiding the payment")


class PaymentOut(BaseModel):
    id: int
    invoice_id: int
    tenant_id: int
    amount: Decimal
    currency_code: str
    method: PaymentMethod
    reference: Optional[str] = None
    status: PaymentStatus
    paid_at: Optional[datetime] = None
    recorded_by: Optional[int] = None
    notes: Optional[str] = None
    created_at: datetime

    # ✅ FIXED: Was Optional["InvoiceOut"]. Typing it as InvoiceOut forced deep
    # nested validation, which read invoice.booking.client (not eager-loaded) and
    # crashed with MissingGreenlet on async sessions. The field is exclude=True
    # and only feeds the computed fields below, so Any is correct and safe.
    invoice: Optional[Any] = Field(default=None, exclude=True)

    @computed_field
    @property
    def invoice_number(self) -> Optional[str]:
        if self.invoice and hasattr(self.invoice, 'invoice_number'):
            return self.invoice.invoice_number
        return None

    @computed_field
    @property
    def booking_id(self) -> Optional[int]:
        if self.invoice and hasattr(self.invoice, 'booking_id'):
            return self.invoice.booking_id
        return None

    @computed_field
    @property
    def client_id(self) -> Optional[int]:
        if (self.invoice and hasattr(self.invoice, 'booking') and self.invoice.booking 
                and hasattr(self.invoice.booking, 'client') and self.invoice.booking.client):
            return getattr(self.invoice.booking.client, 'id', None)
        return None

    @computed_field
    @property
    def client_name(self) -> Optional[str]:
        if (self.invoice and hasattr(self.invoice, 'booking') and self.invoice.booking 
                and hasattr(self.invoice.booking, 'client') and self.invoice.booking.client):
            return getattr(self.invoice.booking.client, 'full_name', None)
        return None

    model_config = {"from_attributes": True}


class PublicPaymentCreate(BaseModel):
    """Payload for public payment gateways (e.g., M-Pesa STK Push)."""
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    currency_code: str = Field(default="KES", min_length=3, max_length=3)
    method: PaymentMethod
    reference: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = Field(default=None, max_length=500)

    @field_validator("currency_code")
    @classmethod
    def normalize_currency_code(cls, v: str) -> str:
        return v.upper()


class PaymentVerificationCreate(BaseModel):
    """Payload for tenants submitting manual payment proofs (M-Pesa/Bank)."""
    target_plan: str = Field(..., max_length=50, description="Target plan: starter, pro, enterprise")
    target_billing_cycle: str = Field("monthly", max_length=20, description="monthly | annual")
    payment_method: PaymentMethod = Field(..., description="mpesa or bank")
    reference_code: str = Field(
        ..., 
        min_length=3, 
        max_length=100, 
        description="M-Pesa transaction code or Bank reference"
    )
    notes: Optional[str] = Field(default=None, max_length=500)


class PaymentVerificationReview(BaseModel):
    """Payload for Super Admins reviewing manual payment proofs."""
    status: VerificationStatus = Field(..., description="The new status: 'approved' or 'rejected'")
    rejection_reason: Optional[str] = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def check_rejection_reason(self):
        """Ensure rejection_reason is provided if status is rejected."""
        if self.status == VerificationStatus.rejected and not self.rejection_reason:
            raise ValueError("rejection_reason is required when rejecting a verification request.")
        return self


class PaymentVerificationOut(BaseModel):
    id: int
    tenant_id: int
    target_plan: str
    target_billing_cycle: str
    payment_method: PaymentMethod
    reference_code: str
    notes: Optional[str] = None
    status: VerificationStatus
    rejection_reason: Optional[str] = None
    reviewed_by_id: Optional[int] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    # ✅ TRUTH-BASED FIX: Explicit standard field. No computed magic.
    # We will populate this manually in the router to guarantee it works.
    tenant_name: Optional[str] = None

    model_config = {"from_attributes": True}

# ✅ DELETED: The bottom import of InvoiceOut and model_rebuild() 
# are no longer needed and remove the circular dependency risk.
