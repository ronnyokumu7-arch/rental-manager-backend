# app/schemas/invoice.py
from datetime import datetime, date
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, computed_field, Field, field_validator

from app.models.invoices import InvoiceStatus
from app.models.payments import PaymentMethod


class InvoiceCreate(BaseModel):
    booking_id: int
    due_date: datetime
    notes: Optional[str] = Field(default=None, max_length=500)
    amount_due: Optional[Decimal] = Field(default=None, ge=0, decimal_places=2)
    currency_code: Optional[str] = Field(default="KES", min_length=3, max_length=3)
    discount_amount: Optional[Decimal] = Field(default=Decimal("0"), ge=0, decimal_places=2)
    discount_reason: Optional[str] = Field(default=None, max_length=500)

    @field_validator("currency_code")
    @classmethod
    def validate_currency_code(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return v.upper()


class InvoiceUpdate(BaseModel):
    notes: Optional[str] = Field(default=None, max_length=500)
    amount_due: Optional[Decimal] = Field(default=None, ge=0, decimal_places=2)
    due_date: Optional[datetime] = None
    currency_code: Optional[str] = Field(default=None, min_length=3, max_length=3)
    discount_amount: Optional[Decimal] = Field(default=None, ge=0, decimal_places=2)
    discount_reason: Optional[str] = Field(default=None, max_length=500)

    @field_validator("currency_code")
    @classmethod
    def validate_currency_code(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return v.upper()


class InvoiceOut(BaseModel):
    id: int
    tenant_id: int
    booking_id: Optional[int] = None
    invoice_number: str
    status: InvoiceStatus
    amount_due: Decimal
    amount_paid: Decimal
    currency_code: str
    due_date: datetime
    paid_at: Optional[datetime] = None
    pdf_path: Optional[str] = None
    notes: Optional[str] = None
    share_token: Optional[str] = None
    share_token_expires_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    discount_amount: Decimal
    discount_reason: Optional[str] = None

    # ✅ FIXED: Was Optional["BookingOut"]. Typing it as BookingOut forced deep
    # nested validation, which read booking.vehicle (not eager-loaded) and
    # crashed with MissingGreenlet on async sessions. The field is exclude=True
    # and only feeds the computed fields below, so Any is correct and safe.
    booking: Optional[Any] = Field(default=None, exclude=True)

    @computed_field
    @property
    def remaining_balance(self) -> Decimal:
        return max(Decimal("0"), self.amount_due - (self.amount_paid or Decimal("0")))

    @computed_field
    @property
    def booking_number(self) -> Optional[str]:
        if self.booking and hasattr(self.booking, 'booking_number'):
            return self.booking.booking_number
        return None

    @computed_field
    @property
    def client_id(self) -> Optional[int]:
        if self.booking and hasattr(self.booking, 'client') and self.booking.client:
            return getattr(self.booking.client, 'id', None)
        return None

    @computed_field
    @property
    def client_name(self) -> Optional[str]:
        if self.booking and hasattr(self.booking, 'client') and self.booking.client:
            return getattr(self.booking.client, 'full_name', None)
        return None

    model_config = {"from_attributes": True}


class PublicPaymentDetails(BaseModel):
    """
    Nested object carrying ONLY the payment methods the tenant has configured
    in their dedicated gateway tables (MpesaConfig, BankAccountConfig, etc.).
    Never fabricates missing fields — strict policy.
    """
    # ── M-Pesa (from MpesaConfig) ───────────────────────────────────
    method_type: Optional[str] = None        # "paybill" | "till" | "pochi"
    business_shortcode: Optional[str] = None # Paybill number
    till_number: Optional[str] = None        # Till or Pochi number
    account_number: Optional[str] = None     # Paybill account reference
    account_name: Optional[str] = None       # Display name for clients

    # ── Airtel Money (from AirtelMoneyConfig) ───────────────────────
    airtel_number: Optional[str] = None

    # ── Bank Transfer (from BankAccountConfig) ──────────────────────
    bank_name: Optional[str] = None
    bank_account_number: Optional[str] = None  # ✅ ADDED: distinct from M-Pesa account_number
    bank_account_name: Optional[str] = None    # ✅ ADDED
    branch_code: Optional[str] = None
    swift_code: Optional[str] = None
    currency: Optional[str] = None

    # ── Fallback (from TenantProfile) ───────────────────────────────
    tenant_phone: Optional[str] = None       # Used for "Send Money" fallback


class PublicPaymentCreate(BaseModel):
    """Client self-reported payment on the public portal."""
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    method: PaymentMethod = Field(..., description="mpesa | manual | bank | airtel_money")
    reference: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = Field(default=None, max_length=500)

    @field_validator("reference")
    @classmethod
    def require_reference_for_mobile_money(cls, v, info):
        method = info.data.get("method")
        if method in (PaymentMethod.mpesa, PaymentMethod.airtel_money) and not (v and v.strip()):
            raise ValueError("Transaction reference is required for M-Pesa and Airtel Money payments")
        return v  # ✅ FIXED: Must return the validated value in Pydantic v2


class PublicInvoiceView(BaseModel):
    """
    ✅ CLEAN CONTRACT: Declares EVERY field the public router returns.
    Previously undeclared fields were silently dropped by Pydantic
    (extra='ignore'), which caused NaN balance, N/A vehicle, and
    "Invalid Date" on the public invoice page.
    """
    id: int
    invoice_number: str
    status: InvoiceStatus
    amount_due: Decimal
    amount_paid: Decimal
    remaining_balance: Decimal
    currency_code: str
    due_date: datetime
    paid_at: Optional[datetime] = None
    created_at: datetime
    discount_amount: Decimal
    discount_reason: Optional[str] = None
    notes: Optional[str] = None
    client_name: Optional[str] = None
    client_phone: Optional[str] = None
    tenant_name: Optional[str] = None
    
    # Vehicle (split for clean rendering)
    vehicle_description: Optional[str] = None
    vehicle_name: Optional[str] = None
    vehicle_plate: Optional[str] = None
    
    # Booking reference
    booking_number: Optional[str] = None
    booking_start_date: Optional[str] = None
    booking_end_date: Optional[str] = None
    
    # ✅ Header Identity (from TenantProfile)
    tenant_logo_url: Optional[str] = None
    tenant_email: Optional[str] = None
    tenant_phone: Optional[str] = None
    
    # ✅ Dynamic Payment Channels (from Gateway Config Tables)
    payment_details: Optional[PublicPaymentDetails] = None

# ✅ DELETED: The bottom import of BookingOut and model_rebuild() 
# are no longer needed and remove the circular dependency risk.
