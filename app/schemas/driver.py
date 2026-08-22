# app/schemas/driver.py
"""
Pydantic schemas for staff drivers (Milestone 2).

✅ SECURITY (PII):
  * DriverListOut NEVER exposes raw id_number / dl_number or document keys —
    list views receive masked values only.
  * DriverOut (detail) carries full PII + document keys; the router gates it
    behind the authenticated tenant scope (role-gating lands with RBAC).
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.models.drivers import DriverEmploymentType, DriverPayMode, DriverStatus


def _mask(value: Optional[str]) -> Optional[str]:
    """PII mask: keep last 4 chars only."""
    if not value:
        return None
    return "***" + value[-4:] if len(value) > 4 else "****"


class DriverBase(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)
    phone: str = Field(min_length=7, max_length=30)
    email: Optional[str] = Field(default=None, max_length=150)
    id_number: str = Field(min_length=4, max_length=50)
    dl_number: str = Field(min_length=4, max_length=50)
    dl_expiry: Optional[date] = None


class DriverCreate(DriverBase):
    # ✅ Staff-first: in_house live; contracted parked but accepted for future
    employment_type: DriverEmploymentType = DriverEmploymentType.in_house
    status: DriverStatus = DriverStatus.available
    pay_mode: DriverPayMode = DriverPayMode.commission

    # Per-driver rate overrides (NULL → tenant service config)
    daily_fee: Optional[Decimal] = Field(default=None, ge=0, decimal_places=2)
    overtime_hourly_fee: Optional[Decimal] = Field(default=None, ge=0, decimal_places=2)
    night_accommodation_fee: Optional[Decimal] = Field(default=None, ge=0, decimal_places=2)
    delivery_commission: Optional[Decimal] = Field(default=None, ge=0, decimal_places=2)

    # Document storage keys (files/vault pipeline — never binaries)
    profile_photo_key: Optional[str] = Field(default=None, max_length=255)
    id_front_key: Optional[str] = Field(default=None, max_length=255)
    id_back_key: Optional[str] = Field(default=None, max_length=255)
    dl_photo_key: Optional[str] = Field(default=None, max_length=255)


class DriverUpdate(BaseModel):
    """All-optional patch. Explicit nulls clear overrides (exclude_unset in router)."""
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=150)
    phone: Optional[str] = Field(default=None, min_length=7, max_length=30)
    email: Optional[str] = Field(default=None, max_length=150)
    id_number: Optional[str] = Field(default=None, min_length=4, max_length=50)
    dl_number: Optional[str] = Field(default=None, min_length=4, max_length=50)
    dl_expiry: Optional[date] = None
    employment_type: Optional[DriverEmploymentType] = None
    status: Optional[DriverStatus] = None
    pay_mode: Optional[DriverPayMode] = None
    daily_fee: Optional[Decimal] = Field(default=None, ge=0, decimal_places=2)
    overtime_hourly_fee: Optional[Decimal] = Field(default=None, ge=0, decimal_places=2)
    night_accommodation_fee: Optional[Decimal] = Field(default=None, ge=0, decimal_places=2)
    delivery_commission: Optional[Decimal] = Field(default=None, ge=0, decimal_places=2)
    profile_photo_key: Optional[str] = Field(default=None, max_length=255)
    id_front_key: Optional[str] = Field(default=None, max_length=255)
    id_back_key: Optional[str] = Field(default=None, max_length=255)
    dl_photo_key: Optional[str] = Field(default=None, max_length=255)


class DriverOut(BaseModel):
    """Full detail — PII + document keys. Tenant-scoped by the router."""
    id: int
    tenant_id: int
    full_name: str
    phone: str
    email: Optional[str] = None
    id_number: str
    dl_number: str
    dl_expiry: Optional[date] = None
    profile_photo_key: Optional[str] = None
    id_front_key: Optional[str] = None
    id_back_key: Optional[str] = None
    dl_photo_key: Optional[str] = None
    employment_type: DriverEmploymentType
    status: DriverStatus
    pay_mode: DriverPayMode
    daily_fee: Optional[Decimal] = None
    overtime_hourly_fee: Optional[Decimal] = None
    night_accommodation_fee: Optional[Decimal] = None
    delivery_commission: Optional[Decimal] = None
    user_id: Optional[int] = None
    is_archived: bool = False
    archived_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DriverListOut(BaseModel):
    """List view — PII masked, no document keys."""
    id: int
    full_name: str
    phone: str
    status: DriverStatus
    employment_type: DriverEmploymentType
    pay_mode: DriverPayMode
    dl_expiry: Optional[date] = None
    daily_fee: Optional[Decimal] = None
    delivery_commission: Optional[Decimal] = None
    is_archived: bool = False
    created_at: datetime
    id_number_masked: Optional[str] = None
    dl_number_masked: Optional[str] = None

    @classmethod
    def from_driver(cls, d) -> "DriverListOut":
        """Explicit mapping from ORM Driver — no magic, no raw PII leak."""
        return cls(
            id=d.id,
            full_name=d.full_name,
            phone=d.phone,
            status=d.status,
            employment_type=d.employment_type,
            pay_mode=d.pay_mode,
            dl_expiry=d.dl_expiry,
            daily_fee=d.daily_fee,
            delivery_commission=d.delivery_commission,
            is_archived=d.is_archived,
            created_at=d.created_at,
            id_number_masked=_mask(d.id_number),
            dl_number_masked=_mask(d.dl_number),
        )
