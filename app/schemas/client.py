from datetime import datetime, date
from typing import Optional, Literal
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from app.models.clients import ClientStatus, IdType, ClientVerificationStatus

# ✅ DRIVING ARRANGEMENT: who is behind the wheel for this client's bookings.
# self_drive  → client's own DL required (docs + vetting)
# own_driver  → client's personal driver (identity now, docs+vetting via driver portal)
# chauffeur   → agency assigns a company driver at booking time
DrivingArrangement = Literal["self_drive", "own_driver", "chauffeur"]


class ClientDriverBlock(BaseModel):
    """
    ✅ PERSONAL DRIVER IDENTITY (own_driver arrangement only).
    Identity data captured at client onboarding; the driver's documents
    and selfie-with-ID are collected later via the driver's OWN vetting
    portal (the driver is usually not present when the client onboarded).
    """
    full_name: str = Field(..., min_length=2, max_length=150)
    phone: str = Field(..., min_length=7, max_length=30)
    id_number: str = Field(..., min_length=4, max_length=50)
    dl_number: str = Field(..., min_length=4, max_length=50)
    dl_expiry: Optional[date] = Field(default=None, description="Must be a future date")
    dl_issued_date: Optional[date] = Field(default=None, description="Must be a past date")

    @field_validator("full_name")
    @classmethod
    def normalize_name(cls, v: str) -> str:
        return " ".join(v.split())

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, v: str) -> str:
        return v.strip()

    @field_validator("id_number", "dl_number")
    @classmethod
    def normalize_doc(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("dl_expiry")
    @classmethod
    def validate_dl_expiry(cls, v: Optional[date]) -> Optional[date]:
        if v is None:
            return None
        if v <= date.today():
            raise ValueError("Driver's license expiry must be a future date")
        return v

    @field_validator("dl_issued_date")
    @classmethod
    def validate_dl_issued(cls, v: Optional[date]) -> Optional[date]:
        if v is None:
            return None
        if v >= date.today():
            raise ValueError("Driver's license issue date must be in the past")
        return v


class ClientBase(BaseModel):
    # ✅ NAME SPLIT: structured names; full_name is concatenated server-side
    first_name: str = Field(..., min_length=1, max_length=120)
    last_name: str = Field(..., min_length=1, max_length=120)

    email: Optional[EmailStr] = Field(default=None, max_length=255)
    phone: str = Field(..., min_length=1, max_length=50)

    # ✅ IDENTITY SLOT: which document `id_number` holds (defaults to national_id)
    id_type: IdType = Field(default=IdType.national_id, description="national_id | passport")
    # ✅ TIGHTENED: everyone's ID is stored — required on ALL new onboarding
    id_number: str = Field(..., min_length=3, max_length=50)

    dl_number: Optional[str] = Field(default=None, max_length=50)
    dl_expiry: Optional[date] = Field(default=None, description="Must be a future date")
    # ✅ NEW: DL issue date → experience derived on read (today - issued)
    dl_issued_date: Optional[date] = Field(default=None, description="Must be a past date")

    residential_address: Optional[str] = None
    work_address: Optional[str] = None
    next_of_kin_name: Optional[str] = Field(default=None, max_length=255)
    next_of_kin_phone: Optional[str] = Field(default=None, max_length=50)

    # ✅ DRIVING ARRANGEMENT (default preserves legacy self-drive behaviour)
    driving_arrangement: DrivingArrangement = "self_drive"
    driver: Optional[ClientDriverBlock] = None

    @field_validator("first_name", "last_name")
    @classmethod
    def normalize_names(cls, v: str) -> str:
        return " ".join(v.split())

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, v: str) -> str:
        """Normalize phone: strip whitespace."""
        return v.strip()

    @field_validator("id_number")
    @classmethod
    def normalize_id_number(cls, v: str) -> str:
        """Normalize ID number: strip whitespace and uppercase."""
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

    @field_validator("dl_issued_date")
    @classmethod
    def validate_dl_issued_date(cls, v: Optional[date]) -> Optional[date]:
        """Ensure DL issue date is in the past (experience source)."""
        if v is None:
            return None
        if v >= date.today():
            raise ValueError("Driver's license issue date must be in the past")
        return v

    @model_validator(mode="after")
    def validate_arrangement_consistency(self):
        """own_driver requires the driver block; other arrangements ignore it."""
        if self.driving_arrangement == "own_driver" and self.driver is None:
            raise ValueError("Driver details are required when 'own_driver' is selected")
        if self.driving_arrangement != "own_driver":
            self.driver = None
        # ✅ DL coherence: issued must precede expiry
        if self.dl_issued_date and self.dl_expiry and self.dl_issued_date >= self.dl_expiry:
            raise ValueError("DL issue date must be before its expiry date")
        return self


class ClientCreate(ClientBase):
    pass


class ClientUpdate(BaseModel):
    """
    ✅ SECURITY: Removed 'status' field.
    Status transitions are controlled by business logic (compliance checks, booking history).
    Document URLs are set via the secure file upload endpoint only.
    ✅ Vetting fields are ALSO server-managed — never client/admin-settable here.
    """
    first_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    last_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    email: Optional[EmailStr] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, min_length=1, max_length=50)

    # ✅ IDENTITY SLOT (optional on update)
    id_type: Optional[IdType] = None
    id_number: Optional[str] = Field(default=None, min_length=3, max_length=50)

    dl_number: Optional[str] = Field(default=None, max_length=50)
    dl_expiry: Optional[date] = Field(default=None, description="Must be a future date")
    dl_issued_date: Optional[date] = Field(default=None, description="Must be a past date")
    residential_address: Optional[str] = None
    work_address: Optional[str] = None
    next_of_kin_name: Optional[str] = Field(default=None, max_length=255)
    next_of_kin_phone: Optional[str] = Field(default=None, max_length=50)
    
    # ✅ Allow updating arrangement later if needed
    driving_arrangement: Optional[DrivingArrangement] = None

    @field_validator("first_name", "last_name", "full_name")
    @classmethod
    def normalize_names(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return " ".join(v.split())

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

    @field_validator("dl_issued_date")
    @classmethod
    def validate_dl_issued_date(cls, v: Optional[date]) -> Optional[date]:
        if v is None:
            return None
        if v >= date.today():
            raise ValueError("Driver's license issue date must be in the past")
        return v


class ClientOut(BaseModel):
    id: int
    tenant_id: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: str
    email: Optional[EmailStr] = None
    phone: str

    # ✅ IDENTITY SLOT
    id_type: IdType = IdType.national_id
    id_number: Optional[str] = None

    dl_number: Optional[str] = None
    dl_expiry: Optional[date] = None
    dl_issued_date: Optional[date] = None
    
    # ✅ DRIVING ARRANGEMENT (exposed for frontend badges)
    driving_arrangement: DrivingArrangement = "self_drive"
    
    status: ClientStatus
    residential_address: Optional[str] = None
    work_address: Optional[str] = None
    next_of_kin_name: Optional[str] = None
    next_of_kin_phone: Optional[str] = None
    avatar_image: Optional[str] = None
    id_image_front: Optional[str] = None
    id_image_back: Optional[str] = None
    dl_image_front: Optional[str] = None

    # ✅ VETTING TRACK (read-only; transitions are server-managed)
    # Token + expiry are NEVER exposed (secret, single-use)
    verification_status: ClientVerificationStatus = ClientVerificationStatus.unverified
    selfie_with_id_image: Optional[str] = None
    vetted_at: Optional[datetime] = None
    rejection_notes: Optional[str] = None

    # ✅ RISK FLAGS (read-only; set by the backend identity engine)
    is_flagged: bool = False
    flag_notes: Optional[str] = None

    is_archived: bool = False
    archived_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
