from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, field_validator

from app.models.vehicles import VehicleStatus


class VehicleBase(BaseModel):
    make: str
    model: str
    year: int
    plate_number: str
    vin: Optional[str] = None
    daily_rate: Decimal
    notes: Optional[str] = None


class VehicleCreate(VehicleBase):
    pass


class VehicleUpdate(BaseModel):
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    plate_number: Optional[str] = None
    vin: Optional[str] = None
    daily_rate: Optional[Decimal] = None
    status: Optional[VehicleStatus] = None
    insurance_doc: Optional[str] = None
    registration_doc: Optional[str] = None
    inspection_doc: Optional[str] = None
    insurance_expiry: Optional[datetime] = None
    notes: Optional[str] = None


class VehicleOut(BaseModel):
    id: int
    tenant_id: int
    make: str
    model: str
    year: int
    plate_number: str
    vin: Optional[str] = None
    status: VehicleStatus
    daily_rate: Decimal
    insurance_doc: Optional[str] = None
    registration_doc: Optional[str] = None
    inspection_doc: Optional[str] = None
    insurance_expiry: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}