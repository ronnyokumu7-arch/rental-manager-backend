from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from app.models.vehicles import VehicleStatus


class VehicleBase(BaseModel):
    """
    Base schema for Agency-managed vehicles.
    daily_rate = What the AGENCY charges the CLIENT.
    """
    make: str = Field(..., min_length=1, max_length=100)
    model: str = Field(..., min_length=1, max_length=100)
    year: int = Field(..., ge=1900, le=datetime.now().year + 1)
    plate_number: str = Field(..., min_length=1, max_length=50)
    vin: Optional[str] = Field(default=None, max_length=50)
    
    # ✅ AGENCY PRICING: What the end-client pays per day
    daily_rate: Decimal = Field(..., gt=0, decimal_places=2)
    
    current_mileage: int = Field(default=0, ge=0)
    next_service_km: Optional[int] = Field(default=None, ge=0)
    
    # ✅ Optional: Shouldn't block onboarding, required for activation later
    insurance_number: Optional[str] = Field(default=None, max_length=100)
    insurance_expiry: Optional[datetime] = None
    inspection_doc: Optional[str] = None
    
    notes: Optional[str] = None

    # ✅ MILESTONE 2: Airport Transfer Support
    supports_airport_transfer: bool = Field(default=False)
    airport_transfer_base_rate: Optional[Decimal] = Field(default=None, gt=0, decimal_places=2)

    # ✅ MILESTONE 3: Wedding Car Hire Support
    supports_wedding_service: bool = Field(default=False)
    wedding_base_rate: Optional[Decimal] = Field(default=None, gt=0, decimal_places=2)

    @field_validator("plate_number")
    @classmethod
    def normalize_plate_number(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("vin")
    @classmethod
    def normalize_vin(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return v.strip().upper()


class VehicleCreate(VehicleBase):
    pass


# ✅ NEW: Investor-specific Vehicle Creation Schema
class InvestorVehicleCreate(BaseModel):
    """
    ✅ Investors only provide physical car details. 
    No pricing fields. Pricing is handled later via the Lease Agreement.
    """
    make: str = Field(..., min_length=1, max_length=100)
    model: str = Field(..., min_length=1, max_length=100)
    year: int = Field(..., ge=1900, le=datetime.now().year + 1)
    plate_number: str = Field(..., min_length=1, max_length=50)
    vin: Optional[str] = Field(default=None, max_length=50)
    
    current_mileage: int = Field(default=0, ge=0)
    next_service_km: Optional[int] = Field(default=None, ge=0)
    
    # ✅ Optional: Shouldn't block onboarding
    insurance_number: Optional[str] = Field(default=None, max_length=100)
    insurance_expiry: Optional[datetime] = None
    inspection_doc: Optional[str] = None
    
    notes: Optional[str] = None

    @field_validator("plate_number")
    @classmethod
    def normalize_plate_number(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("vin")
    @classmethod
    def normalize_vin(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return v.strip().upper()


class VehicleUpdate(BaseModel):
    """
    ✅ Full update schema for AGENCY-OWNED vehicles.
    Agencies can update everything (except status/docs which are handled separately).
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
    inspection_doc: Optional[str] = None
    notes: Optional[str] = None

    supports_airport_transfer: Optional[bool] = None
    airport_transfer_base_rate: Optional[Decimal] = Field(default=None, gt=0, decimal_places=2)
    supports_wedding_service: Optional[bool] = None
    wedding_base_rate: Optional[Decimal] = Field(default=None, gt=0, decimal_places=2)

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


# ✅ NEW: Restricted update schema for INVESTOR-OWNED vehicles
class InvestorVehicleAgencyUpdate(BaseModel):
    """
    ✅ RESTRICTED: What agencies can update on an investor's car.
    Agencies can update operational/financial fields (daily_rate, mileage, services).
    Agencies CANNOT update core identity/ownership fields (plate, VIN, insurance).
    """
    # ✅ ALLOWED: Financial & Operational
    daily_rate: Optional[Decimal] = Field(default=None, gt=0, decimal_places=2)
    current_mileage: Optional[int] = Field(default=None, ge=0)
    next_service_km: Optional[int] = Field(default=None, ge=0)
    notes: Optional[str] = None
    
    # ✅ ALLOWED: Service Toggles
    supports_airport_transfer: Optional[bool] = None
    airport_transfer_base_rate: Optional[Decimal] = Field(default=None, gt=0, decimal_places=2)
    supports_wedding_service: Optional[bool] = None
    wedding_base_rate: Optional[Decimal] = Field(default=None, gt=0, decimal_places=2)


class VehicleOut(VehicleBase):
    id: int
    tenant_id: int
    status: VehicleStatus
    mileage_due: bool = False

    insurance_doc: Optional[str] = None
    registration_doc: Optional[str] = None
    inspection_doc: Optional[str] = None
    is_archived: bool
    archived_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MileageUpdatePayload(BaseModel):
    current_mileage: int = Field(
        ge=0,
        description="New odometer reading (must be >= current mileage)",
    )
    next_service_km: Optional[int] = Field(
        default=None,
        ge=0,
        description="Optional next service interval",
    )
