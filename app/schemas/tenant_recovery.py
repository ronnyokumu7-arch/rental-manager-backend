# app/schemas/tenant_recovery.py

from enum import Enum
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class VerificationMethod(str, Enum):
    email = "email"
    phone = "phone"
    manual_override = "manual_override"


class ChangeAdminEmailPayload(BaseModel):
    """Secure payload for changing a tenant's primary admin email."""
    
    new_email: EmailStr = Field(..., description="The new administrator email address")
    verification_method: VerificationMethod = Field(
        ..., 
        description="Channel used to verify identity (email, phone, or manual override)"
    )
    reason: str = Field(
        ..., 
        min_length=10, 
        max_length=500,
        description="Mandatory justification for this high-risk change (min 10 chars)"
    )
    otp: str | None = Field(
        None, 
        min_length=6, 
        max_length=6,
        description="6-digit OTP sent to selected verification channel (not required for manual_override)"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "new_email": "admin@newdomain.co.ke",
                "verification_method": "phone",
                "reason": "Previous admin left company; domain expired. New admin verified via HR records.",
                "otp": "482917"
            }
        }
    )


class SendResetLinkPayload(BaseModel):
    """Payload for triggering password reset link to tenant admin."""
    
    send_to_email: bool = Field(default=True, description="Send reset link to registered admin email")
    send_to_phone: bool = Field(default=False, description="Send SMS with reset instructions (if phone_verified)")
    custom_message: str | None = Field(
        None, 
        max_length=200,
        description="Optional personalized message included in reset notification"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "send_to_email": True,
                "send_to_phone": False,
                "custom_message": "Hi Jane, please reset your password using the link below. Contact support if you did not request this."
            }
        }
    )


class AdminRecoveryOptionsOut(BaseModel):
    """Response showing available recovery channels and rate limit status."""
    
    admin_email_masked: str = Field(..., description="Masked current admin email (e.g., j***@example.com)")
    admin_phone_masked: str | None = Field(None, description="Masked verified phone (e.g., +254 *** *** 7890) or null if unverified")
    phone_verified: bool = Field(..., description="Whether the admin phone is verified for SMS OTP")
    reset_attempts_remaining: int = Field(..., ge=0, le=3, description="Password reset attempts remaining in current hour")
    email_change_cooldown_minutes: int = Field(..., ge=0, description="Minutes until next admin email change is allowed (0 = no cooldown)")
    last_reset_request_at: str | None = Field(None, description="ISO timestamp of last reset request")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "admin_email_masked": "j***@apexfleet.co.ke",
                "admin_phone_masked": "+254 *** *** 7890",
                "phone_verified": True,
                "reset_attempts_remaining": 2,
                "email_change_cooldown_minutes": 45,
                "last_reset_request_at": "2026-07-12T10:30:00Z"
            }
        }
    )
