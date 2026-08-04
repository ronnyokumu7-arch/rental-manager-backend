from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, field_validator
from app.models.clients import ClientStatus


class ClientBase(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=255)
    email: Optional[EmailStr] = Field(default=None, max_length=255)
    phone: str = Field(..., min_length=1, max_length=50)
    id_number: Optional[str] = Field(default=None, max_length=50)
    dl_number: Optional[str] = Field(default=None, max_length=50)
    dl_expiry: Optional[date] = Field(default=None, description="Must be a future date")
    residential_address: Optional[str] = None
    work_address: Optional[str] = None
    next_of_kin_name: Optional[str] = Field(default=None, max_length=255)
    next_of_kin_phone: Optional[str] = Field(default=None, max_length=50)

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, v: str) -> str:
        """Normalize phone: strip whitespace."""
        return v.strip()

    @field_validator("id_number")
    @classmethod
    def normalize_id_number(cls, v: Optional[str]) -> Optional[str]:
        """Normalize ID number: strip whitespace and uppercase."""
        if v is None:
            return None
        return v.strip().upper()

    @field_validator("dl_number")
    @classmethod
    def normalize_dl_number(cls, v: Optional[str]) -> Optional[str]:
        """Normalize DL number: strip whitespace and uppercase."""
        if v is None:
            return None
        return v.strip().upper()

    @field_validator("dl_expiry")
    @classmethod
    def validate_dl_expiry(cls, v: Optional[date]) -> Optional[date]:
        """Ensure DL expiry is a future date."""
        if v is None:
            return None
        if v <= date.today():
            raise ValueError("Driver's license expiry must be a future date")
        return v


class ClientCreate(ClientBase):
    pass


class ClientUpdate(BaseModel):
    """
    ✅ SECURITY: Removed 'status' field.
    Status transitions are controlled by business logic (compliance checks, booking history).
    Document URLs are set via the secure file upload endpoint only.
    """
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    email: Optional[EmailStr] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, min_length=1, max_length=50)
    id_number: Optional[str] = Field(default=None, max_length=50)
    dl_number: Optional[str] = Field(default=None, max_length=50)
    dl_expiry: Optional[date] = Field(default=None, description="Must be a future date")
    residential_address: Optional[str] = None
    work_address: Optional[str] = None
    next_of_kin_name: Optional[str] = Field(default=None, max_length=255)
    next_of_kin_phone: Optional[str] = Field(default=None, max_length=50)

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return v.strip()

    @field_validator("id_number")
    @classmethod
    def normalize_id_number(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return v.strip().upper()

    @field_validator("dl_number")
    @classmethod
    def normalize_dl_number(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return v.strip().upper()

    @field_validator("dl_expiry")
    @classmethod
    def validate_dl_expiry(cls, v: Optional[date]) -> Optional[date]:
        if v is None:
            return None
        if v <= date.today():
            raise ValueError("Driver's license expiry must be a future date")
        return v


class ClientOut(BaseModel):
    id: int
    tenant_id: int
    full_name: str
    email: Optional[EmailStr] = None
    phone: str
    id_number: Optional[str] = None
    dl_number: Optional[str] = None
    dl_expiry: Optional[date] = None
    status: ClientStatus
    residential_address: Optional[str] = None
    work_address: Optional[str] = None
    next_of_kin_name: Optional[str] = None
    next_of_kin_phone: Optional[str] = None
    avatar_image: Optional[str] = None
    id_image_front: Optional[str] = None
    id_image_back: Optional[str] = None
    dl_image_front: Optional[str] = None
    is_archived: bool = False
    archived_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
