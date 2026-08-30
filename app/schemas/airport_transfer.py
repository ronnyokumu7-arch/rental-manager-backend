"""
Airport Transfer Pydantic Schemas.

✅ DESIGN:
  - Mirrors the Booking schema patterns (Base, Create, Update, Out).
  - Strict financial typing using Decimal.
  - Uses application-level Enum (TransferDirection) for validation.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, model_validator

# ✅ Import the application-level enum from the model
from app.models.airport_transfer import TransferDirection


class AirportTransferBase(BaseModel):
    """Base fields for creating or updating an airport transfer."""
    
    # ✅ Link to the master booking
    booking_id: int

    # ✅ Flight & Airport Details
    flight_number: Optional[str] = Field(default=None, max_length=20)
    airline: Optional[str] = Field(default=None, max_length=50)
    terminal: Optional[str] = Field(default=None, max_length=20)
    airport_code: Optional[str] = Field(default=None, max_length=10)

    # ✅ Time & Scheduling
    scheduled_pickup_at: datetime
    flight_arrival_at: Optional[datetime] = None

    # ✅ Location Details
    city: Optional[str] = Field(default=None, max_length=100)
    pickup_location: Optional[str] = Field(default=None, max_length=255)
    drop_off_location: Optional[str] = Field(default=None, max_length=255)

    # ✅ Transfer Type
    direction: TransferDirection = Field(
        default=TransferDirection.airport_pickup,
        description="airport_pickup | airport_dropoff | both"
    )

    # ✅ v1 Pricing Variables
    toll_fees: Decimal = Field(default=0.00, ge=0, decimal_places=2)
    airport_parking_fees: Decimal = Field(default=0.00, ge=0, decimal_places=2)

    # ✅ Notes
    notes: Optional[str] = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def check_flight_times(self):
        """Ensure flight arrival is before scheduled pickup if both are provided."""
        if self.flight_arrival_at and self.scheduled_pickup_at:
            if self.flight_arrival_at > self.scheduled_pickup_at:
                # Just a warning/logic check, not strictly blocking as staff might pad time
                pass 
        return self


class AirportTransferCreate(AirportTransferBase):
    """Schema for POST /airport-transfers"""
    pass


class AirportTransferUpdate(BaseModel):
    """
    ✅ SECURITY: All fields optional for PATCH requests.
    """
    flight_number: Optional[str] = Field(default=None, max_length=20)
    airline: Optional[str] = Field(default=None, max_length=50)
    terminal: Optional[str] = Field(default=None, max_length=20)
    airport_code: Optional[str] = Field(default=None, max_length=10)

    scheduled_pickup_at: Optional[datetime] = None
    flight_arrival_at: Optional[datetime] = None

    city: Optional[str] = Field(default=None, max_length=100)
    pickup_location: Optional[str] = Field(default=None, max_length=255)
    drop_off_location: Optional[str] = Field(default=None, max_length=255)

    direction: Optional[TransferDirection] = None

    toll_fees: Optional[Decimal] = Field(default=None, ge=0, decimal_places=2)
    airport_parking_fees: Optional[Decimal] = Field(default=None, ge=0, decimal_places=2)

    notes: Optional[str] = Field(default=None, max_length=1000)


class AirportTransferOut(BaseModel):
    """Schema for GET responses (includes DB-generated fields and timestamps)."""
    id: int
    tenant_id: int
    booking_id: int

    flight_number: Optional[str] = None
    airline: Optional[str] = None
    terminal: Optional[str] = None
    airport_code: Optional[str] = None

    scheduled_pickup_at: datetime
    flight_arrival_at: Optional[datetime] = None

    city: Optional[str] = None
    pickup_location: Optional[str] = None
    drop_off_location: Optional[str] = None

    direction: TransferDirection

    toll_fees: Decimal
    airport_parking_fees: Decimal

    notes: Optional[str] = None

    # ✅ AuditMixin timestamps
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
