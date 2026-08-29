from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, Field, model_validator
from app.models.bookings import BookingStatus, CancellationReason

# 💡 Import nested schemas so Pydantic serializes joined relations
from app.schemas.client import ClientOut
from app.schemas.vehicle import VehicleOut
from app.schemas.driver import DriverOut  # ✅ MILESTONE 2: nested driver


class BookingBase(BaseModel):
    client_id: int
    vehicle_id: int
    start_date: datetime
    end_date: datetime
    destination: Optional[str] = Field(default=None, max_length=255)
    pickup_location: Optional[str] = Field(default=None, max_length=255)
    return_location: Optional[str] = Field(default=None, max_length=255)
    
    # ✅ PHASE 1: daily_rate is now optional (server uses vehicle.daily_rate if not provided)
    # If client sends a value, it becomes the effective rate for THIS booking only
    daily_rate: Optional[Decimal] = Field(default=None, gt=0, decimal_places=2)
    
    # ✅ PHASE 1: total_amount is now optional (server computes it via pricing engine)
    total_amount: Optional[Decimal] = Field(default=None, ge=0, decimal_places=2)
    currency_code: str = Field(default="KES", min_length=3, max_length=3)

    # ✅ MILESTONE 1: Service type + exact times
    service_type: str = "selfdrive"
    pickup_at: Optional[datetime] = None
    scheduled_return_at: Optional[datetime] = None

    # ✅ MILESTONE 2: Staff driver assignment (validated tenant-side in router)
    driver_id: Optional[int] = None

    @model_validator(mode="after")
    def check_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot be before start_date")
        return self


class BookingCreate(BookingBase):
    pass


class BookingUpdate(BaseModel):
    """
    ✅ SECURITY: Removed 'status' field.
    Status transitions are controlled by business logic (vehicle pickup, return, cancellation).

    ✅ IMMUTABLE FIELDS: 'client_id', 'vehicle_id', and 'original_end_date' are excluded.
    """
    destination: Optional[str] = Field(default=None, max_length=255)
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    pickup_location: Optional[str] = Field(default=None, max_length=255)
    return_location: Optional[str] = Field(default=None, max_length=255)
    daily_rate: Optional[Decimal] = Field(default=None, gt=0, decimal_places=2)
    total_amount: Optional[Decimal] = Field(default=None, gt=0, decimal_places=2)
    currency_code: Optional[str] = Field(default=None, min_length=3, max_length=3)

    service_type: Optional[str] = None
    pickup_at: Optional[datetime] = None
    scheduled_return_at: Optional[datetime] = None

    driver_id: Optional[int] = None

    @model_validator(mode="after")
    def check_dates(self):
        if self.start_date and self.end_date:
            if self.end_date < self.start_date:
                raise ValueError("end_date cannot be before start_date")
        return self


class CancelBookingPayload(BaseModel):
    """
    ✅ LIFECYCLE: cancel-with-reason. `reason` is validated against the
    CancellationReason enum (str-enum → Pydantic coerces + rejects invalid).
    Terminal status is always `cancelled`; the reason preserves business meaning.
    """
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
    original_end_date: Optional[datetime] = None  # ✅ Immutable audit trail for extensions
    daily_rate: Optional[Decimal] = None
    total_amount: Decimal
    currency_code: str
    status: BookingStatus
    is_archived: bool = False
    archived_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    # ✅ MILESTONE 1: Service type + exact times
    service_type: str
    pickup_at: Optional[datetime] = None
    scheduled_return_at: Optional[datetime] = None
    actual_return_at: Optional[datetime] = None  # ✅ set on complete (late-return reconciliation)
    
    # ✅ LEGACY PRICING SNAPSHOT (kept for old data, no longer used in Phase 1)
    pricing_day_hours: Optional[int] = None
    pricing_grace_minutes: Optional[int] = None
    pricing_overtime_hourly_rate: Optional[Decimal] = None
    
    # ✅ PHASE 1: Self-Drive Pricing Snapshot (immutable after creation)
    billable_days: Optional[int] = None
    computed_total: Optional[Decimal] = None
    manually_adjusted: bool = False
    price_note: Optional[str] = None

    # ✅ LIFECYCLE: cancellation metadata (replaces removed no_show status)
    cancellation_reason: Optional[CancellationReason] = None
    cancelled_at: Optional[datetime] = None
    cancelled_by: Optional[int] = None

    # ✅ MILESTONE 2: Staff driver link
    driver_id: Optional[int] = None

    # 🅿️ PARKED (client drivers): read-only snapshots for contracts
    client_provided_driver: bool = False
    client_driver_name: Optional[str] = None
    client_driver_phone: Optional[str] = None

    # 💡 NESTED RELATIONSHIPS:
    client: Optional[ClientOut] = None
    vehicle: Optional[VehicleOut] = None
    driver: Optional[DriverOut] = None

    model_config = {"from_attributes": True}


# ✅ PHASE 1: Self-Drive Quote Request (simplified for Phase 1)
class BookingQuote(BaseModel):
    vehicle_id: int
    pickup_at: datetime
    return_at: datetime
    driver_id: Optional[int] = None
    daily_rate_override: Optional[Decimal] = Field(
        default=None, 
        gt=0, 
        decimal_places=2,
        description="Override vehicle daily rate for this quote only"
    )


# ✅ EXTENSION PAYLOAD
class ExtendBookingPayload(BaseModel):
    new_end_date: datetime = Field(..., description="Must be after the current end_date")
    extension_reason: Optional[str] = Field(default=None, max_length=500)
