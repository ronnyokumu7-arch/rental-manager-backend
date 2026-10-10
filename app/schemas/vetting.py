# app/schemas/vetting.py
"""
✅ VETTING (identity binding) schemas — public portal + admin review.

Privacy stance mirrors client_invite.py:
  * Public preview exposes branding + first name + remaining steps ONLY.
  * Dead/used/expired tokens → 410 GoneError (no existence leakage).
  * Tokens NEVER appear in any Out schema.
  * Status transitions are server-owned — no status field in any payload.
"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


PersonType = Literal["client", "driver"]

# ✅ Portal wizard step names (drive the frontend step order)
CLIENT_VETTING_STEPS = ["selfie_with_id"]
DRIVER_VETTING_STEPS = ["id_front", "id_back", "dl_front", "selfie_with_id"]


class StartVerificationOut(BaseModel):
    """Admin trigger response — the shareable link + how it was delivered."""
    verification_link: str
    channels_sent: list[str]          # subset of ["email", "whatsapp"]
    expires_at: datetime


class PublicVettingPreviewOut(BaseModel):
    """
    ✅ WHAT THE PUBLIC VETTING PAGE SEES for a VALID token:
    branding + first name + remaining steps. Nothing else.
    Invalid/expired/used tokens → 410 Gone instead.
    """
    person_type: PersonType
    tenant_name: str
    tenant_logo_url: Optional[str] = None
    tenant_phone: Optional[str] = None
    tenant_email: Optional[str] = None
    expires_at: datetime
    person_first_name: str
    steps: list[str]                  # remaining required steps


class VettingUploadOut(BaseModel):
    """Token-scoped slot upload response (slot upsert — one file per slot)."""
    slot: str
    file_ref: str


class VettingSubmitPayload(BaseModel):
    """
    ✅ FINAL VETTING STEP: selfie holding the physical ID.
    Camera-only capture enforced on the frontend; image content-type
    validated at upload time. Server flips status → under_review.
    Documents are NOT re-collected here (one set only — Phase 1 owns them).
    """
    selfie_with_id: str = Field(..., max_length=500)


class VettingReviewPayload(BaseModel):
    """
    Admin review decision.
    approve → verification_status=verified (+ status=active for clients)
    reject  → verification_status=rejected + notes (retryable)
    """
    decision: Literal["approve", "reject"]
    rejection_notes: Optional[str] = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def require_notes_on_reject(self):
        if self.decision == "reject" and not (self.rejection_notes or "").strip():
            raise ValueError("Rejection notes are required so the person knows what to fix")
        return self
