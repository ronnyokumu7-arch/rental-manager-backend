from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from app.models.vehicles import VehicleStatus


class VehicleBase(BaseModel):
    make: str = Field(..., min_length=1, max_length=100)
    model: str = Field(..., min_length=1, max_length=100)
    year: int = Field(..., ge=1900, le=datetime.now().year + 1)
    plate_number: str = Field(..., min_length=1, max_length=50)
    vin: Optional[str] = Field(default=None, max_length=50)
    daily_rate: Decimal = Field(..., gt=0, decimal_places=2)
    current_mileage: int = Field(default=0, ge=0)
    next_service_km: Optional[int] = Field(default=None, ge=0)
    insurance_number: Optional[str] = Field(default=None, max_length=100)
    insurance_expiry: Optional[datetime] = None
    notes: Optional[str] = None

    @field_validator("plate_number")
    @classmethod
    def normalize_plate_number(cls, v: str) -> str:
        """Normalize plate number: strip whitespace and uppercase."""
        return v.strip().upper()

    @field_validator("vin")
    @classmethod
    def normalize_vin(cls, v: Optional[str]) -> Optional[str]:
        """Normalize VIN: strip whitespace and uppercase."""
        if v is None:
            return None
        return v.strip().upper()


class VehicleCreate(VehicleBase):
    pass


class VehicleUpdate(BaseModel):
    """
    ✅ SECURITY: Removed 'status' and document URLs.
    - Status transitions are controlled by business logic (bookings, maintenance mode).
    - Document URLs are set via the secure file upload endpoint only.
    """
    make: Optional[str] = Field(default=None, min_length=1, max_length=100)
    model: Optional[str] = Field(default=None, min_length=1, max_length=100)
    year: Optional[int] = Field(default=None, ge=1900, le=datetime.now().year + 1)
    plate_number: Optional[str] = Field(default=None, min_length=1, max_length=50)
    vin: Optional[str] = Field(default=None, max_length=50)
    daily_rate: Optional[Decimal] = Field(default=None, gt=0, decimal_places=2)
    current_mileage: Optional[int] = Field(default=None, ge=0)
    next_service_km: Optional[int] = Field(default=None, ge=0)
    insurance_number: Optional[str] = Field(default=None, max_length=100)
    insurance_expiry: Optional[datetime] = None
    notes: Optional[str] = None

    @field_validator("plate_number")
    @classmethod
    def normalize_plate_number(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return v.strip().upper()

    @field_validator("vin")
    @classmethod
    def normalize_vin(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return v.strip().upper()


class VehicleOut(VehicleBase):
    id: int
    tenant_id: int
    status: VehicleStatus

    # ✅ LIFECYCLE: return mileage not yet logged (vehicle stays rentable).
    # Replaces the removed awaiting_mileage status — no more stuck cars.
    mileage_due: bool = False

    insurance_doc: Optional[str] = None
    registration_doc: Optional[str] = None
    inspection_doc: Optional[str] = None
    is_archived: bool
    archived_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# =============================================================================
# ✅ MILEAGE UPDATE PAYLOAD: logs return mileage + clears mileage_due
# =============================================================================
class MileageUpdatePayload(BaseModel):
    """
    ✅ Logs the return odometer reading and clears the mileage_due flag.
    Brand new vehicles can have 0 mileage (ge=0).
    The "must be greater than current" validation happens in the router.
    """
    current_mileage: int = Field(
        ge=0,
        description="New odometer reading (must be >= current mileage)",
    )
    next_service_km: Optional[int] = Field(
        default=None,
        ge=0,
        description="Optional next service interval",
    )
