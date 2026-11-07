from datetime import datetime, date
from typing import Optional, Literal
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator, computed_field
from app.models.clients import ClientStatus, IdType, ClientVerificationStatus

# ✅ DRIVING ARRANGEMENT: who drives the rental vehicle.
# self_drive  → client drives; client's DL is required
# own_driver  → client drives with their personal driver; driver's details/docs are required
# chauffeur   → agency supplies and assigns a driver
# `pending` means the applicant has not selected how the vehicle will be
# driven yet.  It is only valid while their account remains pending
# verification; activation rejects it.
DrivingArrangement = Literal["pending", "self_drive", "own_driver", "chauffeur"]


class ClientDriverBlock(BaseModel):
    """
    ✅ PERSONAL DRIVER IDENTITY (own_driver arrangement only).
    The client rents the vehicle for their personal driver to drive; this is
    distinct from a chauffeur booking where the agency supplies the driver.
    """
    full_name: str = Field(..., min_length=2, max_length=150)
    phone: str = Field(..., min_length=7, max_length=30)
    id_number: str = Field(..., min_length=4, max_length=50)
    dl_number: str = Field(..., min_length=4, max_length=50)
    dl_expiry: Optional[date] = Field(default=None, description="Must be a future date")
    dl_issued_date: Optional[date] = Field(default=None, description="Must be a past date")

    # ✅ Read-only image URLs (populated via the client's driver doc
    # upload endpoints — never sent by the client on create/update)
    id_image_front: Optional[str] = None
    dl_image_front: Optional[str] = None

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

    # Driving is selected during verification, not basic account creation.
    driving_arrangement: DrivingArrangement = "pending"
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
        """Validate driving details only when an arrangement is selected."""
        if self.driving_arrangement == "self_drive":
            if not self.dl_number or not self.dl_expiry:
                raise ValueError(
                    "Licence number and expiry date are required for self-drive"
                )
        elif self.driving_arrangement == "own_driver":
            if self.driver is None:
                raise ValueError("Driver details are required when 'own_driver' is selected")
            if not self.driver.dl_expiry:
                raise ValueError(
                    "Driver licence expiry date is required when 'own_driver' is selected"
                )
            if (
                self.driver.dl_issued_date
                and self.driver.dl_issued_date >= self.driver.dl_expiry
            ):
                raise ValueError("Driver licence issue date must be before its expiry date")
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
    # ✅ NEW: allow updating the client-owned driver block
    driver: Optional[ClientDriverBlock] = None

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
    driving_arrangement: DrivingArrangement = "pending"
    
    # ✅ CLIENT-OWNED DRIVER: raw columns used to assemble the nested
    # `driver` computed field. `exclude=True` keeps them out of the JSON
    # response while still letting `from_attributes` read them off the ORM.
    driver_full_name: Optional[str] = Field(default=None, exclude=True)
    driver_phone: Optional[str] = Field(default=None, exclude=True)
    driver_id_number: Optional[str] = Field(default=None, exclude=True)
    driver_dl_number: Optional[str] = Field(default=None, exclude=True)
    driver_dl_expiry: Optional[date] = Field(default=None, exclude=True)
    driver_dl_issued_date: Optional[date] = Field(default=None, exclude=True)
    driver_id_image_front: Optional[str] = Field(default=None, exclude=True)
    driver_dl_image_front: Optional[str] = Field(default=None, exclude=True)
    
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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def driver(self) -> Optional[ClientDriverBlock]:
        """
        ✅ Expose client-owned driver data as a nested `driver` block
        whenever `driving_arrangement == "own_driver"` and at least the
        identity fields are present. Returns None otherwise.
        """
        if self.driving_arrangement != "own_driver":
            return None
        if not (self.driver_full_name and self.driver_phone
                and self.driver_id_number and self.driver_dl_number):
            return None
        return ClientDriverBlock(
            full_name=self.driver_full_name,
            phone=self.driver_phone,
            id_number=self.driver_id_number,
            dl_number=self.driver_dl_number,
            dl_expiry=self.driver_dl_expiry,
            dl_issued_date=self.driver_dl_issued_date,
            id_image_front=self.driver_id_image_front,
            dl_image_front=self.driver_dl_image_front,
        )
