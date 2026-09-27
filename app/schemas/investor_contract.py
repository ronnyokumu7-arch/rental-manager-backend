from datetime import datetime
from decimal import Decimal
from typing import Optional, Any

from pydantic import BaseModel, Field, field_validator, computed_field, model_validator

from app.models.investor_contracts import InvestorContractStatus


class InvestorContractOut(BaseModel):
    id: int
    tenant_id: int
    vehicle_id: int
    booking_id: Optional[int] = None
    contract_number: str
    
    # Lease Terms Snapshot
    lease_rate: Decimal
    lease_rate_type: str
    duration_months: Optional[int] = None
    
    start_date: datetime
    end_date: datetime
    status: InvestorContractStatus
    
    # Document & Sharing
    pdf_path: Optional[str] = None
    share_token: Optional[str] = None
    share_token_expires_at: Optional[datetime] = None
    
    # ✅ Investor Signature Tracking
    signed_by_investor: bool = False
    investor_signed_at: Optional[datetime] = None
    investor_signature_path: Optional[str] = None  # ✅ ADDED
    
    # ✅ Agency Signature Tracking
    signed_by_agency: bool = False
    agency_signed_at: Optional[datetime] = None
    agency_signature_path: Optional[str] = None    # ✅ ADDED
    
    created_at: datetime
    updated_at: datetime

    # Relationships (excluded from JSON output, used for computed fields)
    vehicle: Optional[Any] = Field(default=None, exclude=True)
    tenant: Optional[Any] = Field(default=None, exclude=True)
    booking: Optional[Any] = Field(default=None, exclude=True)

    @computed_field
    @property
    def vehicle_plate(self) -> Optional[str]:
        if self.vehicle:
            return getattr(self.vehicle, "plate_number", None)
        return None

    @computed_field
    @property
    def investor_name(self) -> Optional[str]:
        if self.vehicle and getattr(self.vehicle, "owner", None):
            return getattr(self.vehicle.owner, "full_name", None)
        return None

    model_config = {"from_attributes": True}


class InvestorContractCreate(BaseModel):
    """Payload for agency to generate a new contract."""
    vehicle_id: int
    booking_id: Optional[int] = Field(default=None, description="Required for daily contracts. Null for monthly.")
    duration_months: Optional[int] = Field(default=None, ge=1, le=36, description="Required for monthly contracts.")
    
    @model_validator(mode='after')
    def check_hybrid_logic(self):
        if self.booking_id and self.duration_months:
            raise ValueError("Cannot provide both booking_id (daily) and duration_months (monthly).")
        if not self.booking_id and not self.duration_months:
            raise ValueError("Must provide either booking_id (for daily) or duration_months (for monthly).")
        return self


class InvestorContractSignPayload(BaseModel):
    """Payload for signing the contract (Investor or Agency)."""
    signature: str = Field(..., description="Base64-encoded signature image (PNG/JPEG)")
    signer_role: str = Field(..., pattern="^(investor|agency)$", description="Who is signing: 'investor' or 'agency'")

    @field_validator("signature")
    @classmethod
    def validate_signature(cls, v: str) -> str:
        if not v:
            raise ValueError("Signature cannot be empty")

        if v.startswith("data:"):
            parts = v.split(",", 1)
            if len(parts) != 2:
                raise ValueError("Invalid data URL format")
            v = parts[1]

        try:
            # Validate base64 encoding
            import base64
            decoded = base64.b64decode(v, validate=True)
        except Exception:
            raise ValueError("Invalid base64 encoding")

        # Check size limit (2MB)
        max_size = 2 * 1024 * 1024
        if len(decoded) > max_size:
            raise ValueError("Signature image too large. Maximum size is 2MB")

        # Check magic bytes for PNG or JPEG
        if not (decoded.startswith(b"\x89PNG") or decoded.startswith(b"\xff\xd8\xff")):
            raise ValueError("Signature must be a PNG or JPEG image")

        return v
