# app/schemas/vetting.py
"""
✅ VETTING (identity binding) schemas — public portal + admin review.

Privacy stance mirrors client_invite.py:
  * Public preview exposes branding and the token owner's saved verification
    details/documents so an interrupted owner can resume the same submission.
  * Dead/used/expired tokens → 410 GoneError (no existence leakage).
  * Tokens NEVER appear in any Out schema.
  * Status transitions are server-owned — no status field in any payload.
"""
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


PersonType = Literal["client", "driver"]

# ✅ Portal wizard step names (drive the frontend step order)
CLIENT_VETTING_STEPS = ["driving_details", "documents", "selfie_with_id"]
DRIVER_VETTING_STEPS = ["selfie_with_id"]


class StartVerificationOut(BaseModel):
    """Admin trigger response — the shareable link + how it was delivered."""
    verification_link: str
    channels_sent: list[str]          # subset of ["email", "whatsapp"]
    expires_at: datetime


class PublicVettingPreviewOut(BaseModel):
    """
    What the public vetting page sees for a valid bearer token: branding,
    first name, and that person's saved verification details for resumption.
    Invalid/expired/used tokens → 410 Gone instead.
    """
    person_type: PersonType
    tenant_name: str
    tenant_logo_url: Optional[str] = None
    tenant_phone: Optional[str] = None
    tenant_email: Optional[str] = None
    expires_at: datetime
    person_first_name: str
    id_front_uploaded: bool = False
    driving_arrangement: Optional[Literal["self_drive", "own_driver", "chauffeur"]] = None
    dl_number: Optional[str] = None
    dl_expiry: Optional[date] = None
    dl_issued_date: Optional[date] = None
    driver_full_name: Optional[str] = None
    driver_phone: Optional[str] = None
    driver_id_number: Optional[str] = None
    driver_dl_number: Optional[str] = None
    driver_dl_expiry: Optional[date] = None
    driver_dl_issued_date: Optional[date] = None
    uploaded_slots: list[
        Literal["id_front", "dl_front", "driver_id_front", "driver_dl_front"]
    ] = Field(default_factory=list)
    selfie_uploaded: bool = False
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


class VettingDrivingDetails(BaseModel):
    """Driving information collected only after basic client intake."""
    driving_arrangement: Literal["self_drive", "own_driver", "chauffeur"]
    dl_number: Optional[str] = Field(default=None, max_length=50)
    dl_expiry: Optional[date] = None
    dl_issued_date: Optional[date] = None
    driver_full_name: Optional[str] = Field(default=None, min_length=2, max_length=150)
    driver_phone: Optional[str] = Field(default=None, min_length=7, max_length=30)
    driver_id_number: Optional[str] = Field(default=None, min_length=4, max_length=50)
    driver_dl_number: Optional[str] = Field(default=None, min_length=4, max_length=50)
    driver_dl_expiry: Optional[date] = None
    driver_dl_issued_date: Optional[date] = None

    @model_validator(mode="after")
    def validate_arrangement_details(self):
        if self.driving_arrangement == "self_drive":
            if not self.dl_number or not self.dl_expiry:
                raise ValueError("Licence number and expiry date are required for self-drive")
            if self.dl_expiry <= date.today():
                raise ValueError("Licence expiry date must be in the future")
            if self.dl_issued_date and self.dl_issued_date >= date.today():
                raise ValueError("Licence issue date must be in the past")
            if self.dl_issued_date and self.dl_issued_date >= self.dl_expiry:
                raise ValueError("Licence issue date must be before its expiry date")
        elif self.driving_arrangement == "own_driver":
            required = (
                "driver_full_name", "driver_phone", "driver_id_number",
                "driver_dl_number", "driver_dl_expiry",
            )
            if any(not getattr(self, field) for field in required):
                raise ValueError("Complete personal-driver details are required for My Driver")
            if self.driver_dl_expiry and self.driver_dl_expiry <= date.today():
                raise ValueError("Personal-driver licence expiry date must be in the future")
            if self.driver_dl_issued_date and self.driver_dl_issued_date >= date.today():
                raise ValueError("Personal-driver licence issue date must be in the past")
            if self.driver_dl_issued_date and self.driver_dl_expiry and self.driver_dl_issued_date >= self.driver_dl_expiry:
                raise ValueError("Personal-driver licence issue date must be before its expiry date")
        return self


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
