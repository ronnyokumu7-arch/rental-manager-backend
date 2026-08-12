from datetime import datetime, date
from decimal import Decimal
from typing import Any, Optional # ✅ Added Any

from pydantic import BaseModel, computed_field, Field, field_validator

from app.models.invoices import InvoiceStatus


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
    vehicle_description: Optional[str] = None
    booking_number: Optional[str] = None
    booking_start_date: Optional[str] = None
    booking_end_date: Optional[str] = None

# ✅ DELETED: The bottom import of BookingOut and model_rebuild() 
# are no longer needed and remove the circular dependency risk.
