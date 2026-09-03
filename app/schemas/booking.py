from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, model_validator
from app.models.bookings import BookingStatus, CancellationReason

# 💡 Import nested schemas so Pydantic serializes joined relations
from app.schemas.client import ClientOut
from app.schemas.vehicle import VehicleOut
from app.schemas.driver import DriverOut


class BookingBase(BaseModel):
    """
    ✅ CONTRACT v2: the exact pair (pickup_at / scheduled_return_at) is the
    primary input. The legacy pair (start_date / end_date) is accepted as a
    fallback alias during frontend migration. All optional → factory applies
    defaults (pickup = now, return = pickup + 1 day).
    ✅ Money fields removed: the server is the only source of truth for price.
    """
    client_id: int
    vehicle_id: int

    # Legacy alias pair (optional now; factory falls back to it, then defaults)
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None

    destination: Optional[str] = Field(default=None, max_length=255)
    pickup_location: Optional[str] = Field(default=None, max_length=255)
    return_location: Optional[str] = Field(default=None, max_length=255)

    currency_code: str = Field(default="KES", min_length=3, max_length=3)

    # ✅ MILESTONE 1: Service type + exact times (primary input)
    service_type: str = "selfdrive"
    pickup_at: Optional[datetime] = None
    scheduled_return_at: Optional[datetime] = None

    # ✅ MILESTONE 2: Staff driver assignment (validated tenant-side)
    driver_id: Optional[int] = None

    # ✅ MILESTONE 2: Airport Transfer add-ons
    toll_fees: Decimal = Field(default=0.00, ge=0, decimal_places=2)
    parking_fees: Decimal = Field(default=0.00, ge=0, decimal_places=2)

    # ✅ MILESTONE 3: Service-specific details (JSON)
    service_details: Optional[Dict[str, Any]] = Field(default=None)

    @model_validator(mode="after")
    def check_dates(self):
        # ✅ STRICT: equality now rejected here (DB constraint is strict;
        # previously this mismatch produced 500s instead of 422s)
        if self.start_date is not None and self.end_date is not None:
            if self.end_date <= self.start_date:
                raise ValueError("end_date must be strictly after start_date")
        return self


class BookingCreate(BookingBase):
    pass


class BookingUpdate(BaseModel):
    """
    ✅ SECURITY: no status field.
    ✅ CONTRACT v2: ALL datetime and money fields removed. Schedule or price
    changes go through the booking factory change endpoints only
    (POST /bookings/{id}/changes[/quote]).
    """
    destination: Optional[str] = Field(default=None, max_length=255)
    pickup_location: Optional[str] = Field(default=None, max_length=255)
    return_location: Optional[str] = Field(default=None, max_length=255)
    driver_id: Optional[int] = None
    service_details: Optional[Dict[str, Any]] = None


class CancelBookingPayload(BaseModel):
    reason: CancellationReason = Field(
        ..., description="client_cancelled | agency_cancelled | no_show | expired_unpaid",
    )
    note: Optional[str] = Field(default=None, max_length=500)


class BookingOut(BaseModel):
    id: int
    tenant_id: int
    booking_number: Optional[str] = None
    client_id: int
    vehicle_id: int
    destination: Optional[str] = None
    pickup_location: Optional[str] = None
    return_location: Optional[str] = None
    start_date: datetime
    end_date: datetime
    original_end_date: Optional[datetime] = None
    daily_rate: Optional[Decimal] = None
    total_amount: Decimal
    currency_code: str
    status: BookingStatus
    is_archived: bool = False
    archived_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    service_type: str
    pickup_at: Optional[datetime] = None
    scheduled_return_at: Optional[datetime] = None
    actual_return_at: Optional[datetime] = None

    pricing_day_hours: Optional[int] = None
    pricing_grace_minutes: Optional[int] = None
    pricing_overtime_hourly_rate: Optional[Decimal] = None

    billable_days: Optional[int] = None
    computed_total: Optional[Decimal] = None
    manually_adjusted: bool = False
    price_note: Optional[str] = None

    toll_fees: Decimal = Field(default=0.00, ge=0, decimal_places=2)
    parking_fees: Decimal = Field(default=0.00, ge=0, decimal_places=2)

    cancellation_reason: Optional[CancellationReason] = None
    cancelled_at: Optional[datetime] = None
    cancelled_by: Optional[int] = None

    driver_id: Optional[int] = None

    client_provided_driver: bool = False
    client_driver_name: Optional[str] = None
    client_driver_phone: Optional[str] = None

    service_details: Optional[Dict[str, Any]] = None

    client: Optional[ClientOut] = None
    vehicle: Optional[VehicleOut] = None
    driver: Optional[DriverOut] = None

    client_name: Optional[str] = None
    client_phone: Optional[str] = None
    vehicle_plate: Optional[str] = None
    vehicle_name: Optional[str] = None

    model_config = {"from_attributes": True}


# ✅ Unified Quote Request (times optional → factory defaults now / +1d)
class BookingQuote(BaseModel):
    vehicle_id: int
    pickup_at: Optional[datetime] = None
    return_at: Optional[datetime] = None
    service_type: str = "selfdrive"
    driver_id: Optional[int] = None
    toll_fees: Decimal = Field(default=0.00, ge=0, decimal_places=2)
    parking_fees: Decimal = Field(default=0.00, ge=0, decimal_places=2)
    service_details: Optional[Dict[str, Any]] = None
    # ✅ daily_rate_override REMOVED — rates come only from vehicle/driver config.


# ✅ CHANGE PAYLOAD (extend / reduce / reschedule — factory classifies)
class ChangeBookingPayload(BaseModel):
    new_pickup_at: Optional[datetime] = None
    new_return_at: Optional[datetime] = None
    note: Optional[str] = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def check_something(self):
        if self.new_pickup_at is None and self.new_return_at is None:
            raise ValueError("Provide new_pickup_at and/or new_return_at")
        return self


# ✅ LEGACY (kept for existing extension endpoint compatibility)
class ExtendBookingPayload(BaseModel):
    new_end_date: datetime = Field(..., description="Must be after the current end_date")
    extension_reason: Optional[str] = Field(default=None, max_length=500)


# =============================================================================
# ✅ QUOTE RESPONSE CONTRACT (what the frontend renders verbatim)
# =============================================================================
class QuoteLineOut(BaseModel):
    description: str
    quantity: str
    amount: Decimal


class BookingQuoteOut(BaseModel):
    service_type: str
    pickup_at: str            # platform ISO with offset — render as-is
    scheduled_return_at: str
    billable_days: Optional[int] = None
    daily_rate: Optional[Decimal] = None
    lines: List[QuoteLineOut] = []
    total: Decimal
    currency_code: str


class ChangeSideOut(BaseModel):
    pickup_at: str
    scheduled_return_at: str
    billable_days: Optional[int] = None
    total: Decimal
    lines: List[QuoteLineOut] = []


class ChangeQuoteOut(BaseModel):
    kind: str                 # extend | reduce | reschedule
    current: ChangeSideOut
    new: ChangeSideOut
    delta_days: int
    delta_amount: Decimal
    direction: str            # charge | credit | none
    new_total: Decimal
    currency_code: str
