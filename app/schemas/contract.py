# app/schemas/contract.py

import base64
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, computed_field, Field, field_validator

from app.models.contracts import ContractStatus


class ContractOut(BaseModel):
    id: int
    booking_id: int
    tenant_id: int
    contract_number: str
    status: ContractStatus
    pdf_path: Optional[str] = None
    signature_image_path: Optional[str] = None
    signed_at: Optional[datetime] = None
    share_token: Optional[str] = None
    share_token_expires_at: Optional[datetime] = None
    signed_by_client: bool = False
    client_signed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    # ✅ FIXED: Was Optional["BookingOut"]. Typing it as BookingOut forced deep
    # nested validation, which read booking.vehicle (not eager-loaded) and
    # crashed with MissingGreenlet on async sessions. The field is exclude=True
    # and only feeds the computed fields below, so Any is correct and safe.
    booking: Optional[Any] = Field(default=None, exclude=True)

    @computed_field
    @property
    def booking_number(self) -> Optional[str]:
        """Extract booking number from linked booking."""
        if self.booking and hasattr(self.booking, "booking_number"):
            return self.booking.booking_number
        return None

    @computed_field
    @property
    def client_id(self) -> Optional[int]:
        """Extract client ID from the linked booking's client."""
        if self.booking and hasattr(self.booking, "client") and self.booking.client:
            return getattr(self.booking.client, "id", None)
        return None

    @computed_field
    @property
    def client_name(self) -> Optional[str]:
        """Extract client name from the linked booking's client."""
        if self.booking and hasattr(self.booking, "client") and self.booking.client:
            return getattr(self.booking.client, "full_name", None)
        return None

    model_config = {"from_attributes": True}


class PublicContractView(BaseModel):
    """
    Schema for public contract viewing (no auth required).
    Only exposes data necessary for the client to review and sign.
    """
    contract_number: str
    booking_id: int
    booking_number: Optional[str] = None
    tenant_name: str
    
    # ✅ NEW: Owning tenant's branding (auto-resolved from the contract's tenant,
    # NOT from the logged-in session). Powers the public signing page header.
    tenant_logo_url: Optional[str] = None
    tenant_address: Optional[str] = None
    tenant_phone: Optional[str] = None
    tenant_email: Optional[str] = None
    
    client_name: str
    id_number: Optional[str] = None
    vehicle_make: str
    vehicle_model: str
    vehicle_plate: str
    start_date: str
    end_date: str
    total_amount: str
    currency_code: str
    status: ContractStatus
    signed_by_client: bool
    created_at: datetime
    
    # ✅ MILESTONE 2: Assigned driver (null for self-drive bookings)
    driver_name: Optional[str] = None
    driver_phone: Optional[str] = None
    driver_dl_number: Optional[str] = None

class ContractSignPayload(BaseModel):
    """
    Payload for client signature submission.
    Signature must be a valid base64-encoded image (PNG/JPEG).
    """
    signature: str = Field(
        ...,
        description="Base64-encoded signature image (PNG or JPEG, max 2MB)"
    )

    @field_validator("signature")
    @classmethod
    def validate_signature(cls, v: str) -> str:
        """Validate that signature is valid base64 and within size limits."""
        if not v:
            raise ValueError("Signature cannot be empty")

        # Check if it's a data URL (e.g., "data:image/png;base64,...")
        if v.startswith("data:"):
            # Extract the base64 part after the comma
            parts = v.split(",", 1)
            if len(parts) != 2:
                raise ValueError("Invalid data URL format")
            v = parts[1]

        # Validate base64 encoding
        try:
            decoded = base64.b64decode(v, validate=True)
        except Exception:
            raise ValueError("Invalid base64 encoding")

        # Check size limit (2MB)
        max_size = 2 * 1024 * 1024  # 2MB
        if len(decoded) > max_size:
            raise ValueError("Signature image too large. Maximum size is 2MB")

        # Check magic bytes for PNG or JPEG
        if not (decoded.startswith(b"\x89PNG") or decoded.startswith(b"\xff\xd8\xff")):
            raise ValueError("Signature must be a PNG or JPEG image")

        return v
