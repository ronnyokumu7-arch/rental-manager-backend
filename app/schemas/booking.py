from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, Field, model_validator
from app.models.bookings import BookingStatus

# 💡 Import nested schemas so Pydantic serializes joined relations
from app.schemas.client import ClientOut
from app.schemas.vehicle import VehicleOut


class BookingBase(BaseModel):
    client_id: int
    vehicle_id: int
    start_date: datetime
    end_date: datetime
    destination: Optional[str] = Field(default=None, max_length=255)
    pickup_location: Optional[str] = Field(default=None, max_length=255)
    return_location: Optional[str] = Field(default=None, max_length=255)
    daily_rate: Optional[Decimal] = Field(default=None, gt=0, decimal_places=2)
    total_amount: Decimal = Field(gt=0, decimal_places=2)
    currency_code: str = Field(default="KES", min_length=3, max_length=3)

    @model_validator(mode="after")
    def check_dates(self):
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self


class BookingCreate(BookingBase):
    pass


class BookingUpdate(BaseModel):
    """
    ✅ SECURITY: Removed 'status' field.
    Status transitions are controlled by business logic (vehicle pickup, return, cancellation).
    
    ✅ IMMUTABLE FIELDS: 'client_id', 'vehicle_id', and 'original_end_date' are excluded.
    These are set at creation or by the extension logic, not by direct updates.
    """
    destination: Optional[str] = Field(default=None, max_length=255)
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    pickup_location: Optional[str] = Field(default=None, max_length=255)
    return_location: Optional[str] = Field(default=None, max_length=255)
    daily_rate: Optional[Decimal] = Field(default=None, gt=0, decimal_places=2)
    total_amount: Optional[Decimal] = Field(default=None, gt=0, decimal_places=2)
    currency_code: Optional[str] = Field(default=None, min_length=3, max_length=3)

    @model_validator(mode="after")
    def check_dates(self):
        """Validate date range if both dates are provided."""
        if self.start_date and self.end_date:
            if self.end_date <= self.start_date:
                raise ValueError("end_date must be after start_date")
        return self


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

    # 💡 NESTED RELATIONSHIPS:
    client: Optional[ClientOut] = None
    vehicle: Optional[VehicleOut] = None

    model_config = {"from_attributes": True}


# ✅ EXTENSION PAYLOAD: For Milestone 2 Booking Extensions
class ExtendBookingPayload(BaseModel):
    """
    ✅ VALIDATION: Ensures new_end_date is after the CURRENT end_date.
    The router will compare this against the booking's actual end_date.
    """
    new_end_date: datetime = Field(..., description="Must be after the current end_date")
    extension_reason: Optional[str] = Field(default=None, max_length=500)
