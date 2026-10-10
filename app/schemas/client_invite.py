# app/schemas/client_invite.py
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.client_invite import ClientInviteStatus
from app.models.clients import IdType
from app.schemas.client import ClientBase


class ClientInviteCreate(BaseModel):
    """
    Tenant requests a single-use onboarding link.
    (Empty body is valid — ttl defaults to 7 days.)

    ✅ expected_name / expected_phone are OPTIONAL and informational only:
    they tell the tenant WHO they're expecting. Never enforced at intake.
    """
    ttl_days: int = Field(
        default=7, ge=1, le=30,
        description="How many days the link stays valid (1–30)",
    )
    expected_name: Optional[str] = Field(default=None, max_length=255)
    expected_phone: Optional[str] = Field(default=None, max_length=50)

    @field_validator("expected_name", "expected_phone")
    @classmethod
    def _blank_to_none(cls, v: Optional[str]) -> Optional[str]:
        """Treat empty strings as absent (clean NULLs in the DB)."""
        if v is None:
            return None
        v = v.strip()
        return v or None


class ClientInviteOut(BaseModel):
    """
    Invite ledger row for the tenant UI.
    `is_expired` / `is_live` are read-time properties on the model —
    Pydantic picks them up via from_attributes, no cleanup job needed.

    ✅ MILESTONE: `uploaded_files` exposes per-slot upload progress
    (keys: avatar | id_front | id_back | dl_front) so the tenant can see
    how far the invitee got before submitting. URLs are tenant-owned
    (authenticated storage), safe to expose here.
    """
    id: int
    tenant_id: int
    token: str                      # frontend builds {origin}/invite/{token}
    status: ClientInviteStatus
    expires_at: datetime
    expected_name: Optional[str] = None     # ✅ who we're expecting
    expected_phone: Optional[str] = None    # ✅ who we're expecting
    accepted_client_id: Optional[int] = None
    created_at: datetime
    is_expired: bool = False
    is_live: bool = False

    # ✅ MILESTONE: per-slot upload progress for the invite ledger
    uploaded_files: Optional[dict] = None

    model_config = {"from_attributes": True}


class PublicInvitePreviewOut(BaseModel):
    """
    ✅ WHAT THE PUBLIC PAGE SEES for a VALID invite:
    agency branding + expiry notice. Nothing sensitive.
    (expected_* and uploaded_files are intentionally NOT exposed here — privacy.)
    Invalid/expired/revoked invites → endpoint returns 410 Gone instead.
    """
    tenant_name: str
    tenant_logo_url: Optional[str] = None
    tenant_phone: Optional[str] = None
    tenant_email: Optional[str] = None
    expires_at: datetime


class ClientIntakeCreate(ClientBase):
    """
    ✅ PUBLIC ONBOARDING SUBMISSION.
    Inherits the upgraded ClientBase: name split, required ID slot,
    driving arrangement + optional driver block, all normalizers.

    ✅ TIGHTENED DOCUMENT SLOTS: the invitee is holding their own ID, so
    ID front + back are REQUIRED at intake. DL front is enforced server-side
    for self_drive arrangements (ValidationFailedError with field_errors).

    Security: status / is_flagged / vetting fields are NOT in this schema —
    the server hardcodes status=pending, verification_status=unverified and
    computes risk flags itself.
    """
    id_type: IdType = Field(
        ..., description="Choose exactly one: national_id | passport"
    )
    id_number: str = Field(..., min_length=3, max_length=50)

    # ✅ DOCUMENT URLS (uploaded first via POST /clients/invite/{token}/upload,
    # then passed here so they're stored on the client record)
    avatar_image: Optional[str] = Field(default=None, max_length=500)
    id_image_front: str = Field(..., max_length=500)
    id_image_back: str = Field(..., max_length=500)
    dl_image_front: Optional[str] = Field(default=None, max_length=500)
