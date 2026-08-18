# app/schemas/client_invite.py
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.client_invite import ClientInviteStatus
from app.models.clients import IdType
from app.schemas.client import ClientBase


class ClientInviteCreate(BaseModel):
    """
    Tenant requests a single-use onboarding link.
    (Empty body is valid — ttl defaults to 7 days.)
    """
    ttl_days: int = Field(
        default=7, ge=1, le=30,
        description="How many days the link stays valid (1–30)",
    )


class ClientInviteOut(BaseModel):
    """
    Invite ledger row for the tenant UI.
    `is_expired` / `is_live` are read-time properties on the model —
    Pydantic picks them up via from_attributes, no cleanup job needed.
    """
    id: int
    tenant_id: int
    token: str                      # frontend builds {origin}/invite/{token}
    status: ClientInviteStatus
    expires_at: datetime
    accepted_client_id: Optional[int] = None
    created_at: datetime
    is_expired: bool = False
    is_live: bool = False

    model_config = {"from_attributes": True}


class PublicInvitePreviewOut(BaseModel):
    """
    ✅ WHAT THE PUBLIC PAGE SEES for a VALID invite:
    agency branding + expiry notice. Nothing sensitive.
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
    Inherits all ClientBase fields + normalizers (phone strip, id/dl uppercase),
    but TIGHTENS the identity slot: the client MUST pick one document
    and provide its number to complete onboarding.

    Security: status / is_flagged are NOT in this schema — the server
    hardcodes status=pending and computes risk flags itself.
    """
    id_type: IdType = Field(
        ..., description="Choose exactly one: national_id | passport"
    )
    id_number: str = Field(..., min_length=3, max_length=50)
